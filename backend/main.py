"""Backend: REST API, CRUD истории в PostgreSQL, обращение к web-service."""
import logging
import os
from datetime import datetime

import httpx
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

app = FastAPI(title="Погода и климат — Backend", version="1.0.0")
log = logging.getLogger(__name__)
WEB_SERVICE = os.getenv("WEB_SERVICE_URL", "http://web-service:8001")


class WeatherInput(BaseModel):
    city: str = Field(min_length=2, max_length=100)
    location_id: int | None = Field(default=None, gt=0)

    @field_validator("city")
    @classmethod
    def strip_city(cls, value):
        value = value.strip()
        if len(value) < 2:
            raise ValueError("Введите название города")
        return value


class NoteInput(BaseModel):
    note: str = Field(max_length=500)


class Snapshot(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    requested_city: str = Field(min_length=2, max_length=100)
    city: str = Field(min_length=1, max_length=100)
    country: str = Field(max_length=100)
    region: str = Field(default="", max_length=150)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    temperature: float
    feels_like: float
    humidity: int = Field(ge=0, le=100)
    wind_speed: float = Field(ge=0)
    weather_code: int
    description: str = Field(max_length=100)
    observed_at: AwareDatetime
    source: str = Field(max_length=100)
    source_url: str


class Record(Snapshot):
    id: int
    requested_at: datetime
    note: str
    is_demo: bool


class History(BaseModel):
    items: list[Record]
    total: int
    limit: int
    offset: int


def connect():
    return psycopg.connect(host=os.getenv("DB_HOST", "db"), port=os.getenv("DB_PORT", "5432"),
                           dbname=os.getenv("DB_NAME", "weather"), user=os.getenv("DB_USER", "weather"),
                           password=os.getenv("DB_PASSWORD", "weather_local_lab"),
                           connect_timeout=4, options="-c statement_timeout=5000", row_factory=dict_row)


@app.exception_handler(psycopg.Error)
async def database_error(_request, exc):
    log.error("Database error: %s", type(exc).__name__)
    return JSONResponse(status_code=503, content={"detail": "База данных недоступна. Повторите запрос позже."})


def service_get(path: str, params: dict):
    try:
        with httpx.Client(timeout=httpx.Timeout(28, connect=3)) as client:
            response = client.get(f"{WEB_SERVICE}{path}", params=params)
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", "Ошибка погодного сервиса.")
            except (ValueError, AttributeError):
                detail = "Ошибка погодного сервиса."
            status = response.status_code if response.status_code in (404, 422, 502, 503, 504) else 502
            raise HTTPException(status, detail)
        return response.json()
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Погодный сервис не ответил вовремя.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Погодный сервис недоступен или вернул неверные данные.") from exc


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return """<!doctype html><html lang="ru"><meta charset="utf-8"><title>Backend</title>
    <body style="font:18px system-ui;max-width:800px;margin:60px auto;padding:20px"><h1>Backend приложения</h1>
    <p>Связывает интерфейс, PostgreSQL и погодный веб-сервис.</p>
    <p><a href="/docs">Интерактивная документация REST API</a> · <a href="/health">Состояние БД</a></p>
    <p><a href="/api/history">Прочитать историю из PostgreSQL</a></p>
    <p>POST /api/weather — получить и сохранить погоду; PATCH /api/history/{id} — изменить заметку;
    DELETE /api/history/{id} — удалить запись.</p></body></html>"""


@app.get("/health", tags=["Состояние"])
def health():
    with connect() as conn:
        conn.execute("SELECT id FROM weather_requests LIMIT 1")
    return {"status": "ok", "service": "backend", "database": "ok"}


@app.get("/api/cities", tags=["Погода"])
def cities(q: str = Query(min_length=2, max_length=100)):
    return service_get("/cities", {"q": q})


@app.post("/api/weather", response_model=Record, status_code=201, tags=["Погода"])
def weather(body: WeatherInput):
    try:
        snapshot = Snapshot.model_validate(service_get("/weather", body.model_dump(exclude_none=True)))
    except ValidationError as exc:
        raise HTTPException(502, "Погодный сервис вернул неполные или некорректные данные.") from exc
    data = snapshot.model_dump()
    # Имена полей принадлежат нашей модели, все значения передаются параметрами SQL.
    columns = ", ".join(data)
    placeholders = ", ".join(["%s"] * len(data))
    with connect() as conn:
        row = conn.execute(f"INSERT INTO weather_requests ({columns}) VALUES ({placeholders}) RETURNING *",
                           list(data.values())).fetchone()
    return row


@app.get("/api/history", response_model=History, tags=["История"])
def history(limit: int = Query(10, ge=1, le=100), offset: int = Query(0, ge=0),
            city: str = Query("", max_length=100)):
    # Пользовательский поиск трактуется буквально, без шаблонов SQL LIKE.
    query = city.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{query}%"
    with connect() as conn:
        # Согласованный снимок для списка и счетчика при параллельных изменениях.
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        total = conn.execute("SELECT count(*) AS total FROM weather_requests WHERE city ILIKE %s", (pattern,)).fetchone()["total"]
        rows = conn.execute("SELECT * FROM weather_requests WHERE city ILIKE %s ORDER BY requested_at DESC, id DESC LIMIT %s OFFSET %s",
                            (pattern, limit, offset)).fetchall()
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


@app.get("/api/history/{record_id}", response_model=Record, tags=["История"])
def get_record(record_id: int):
    with connect() as conn:
        row = conn.execute("SELECT * FROM weather_requests WHERE id = %s", (record_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Запись не найдена.")
    return row


@app.patch("/api/history/{record_id}", response_model=Record, tags=["История"])
def update_note(record_id: int, body: NoteInput):
    with connect() as conn:
        row = conn.execute("UPDATE weather_requests SET note = %s WHERE id = %s RETURNING *",
                           (body.note.strip(), record_id)).fetchone()
    if row is None:
        raise HTTPException(404, "Запись не найдена.")
    return row


@app.delete("/api/history/{record_id}", status_code=204, tags=["История"])
def delete_record(record_id: int):
    with connect() as conn:
        row = conn.execute("DELETE FROM weather_requests WHERE id = %s RETURNING id", (record_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Запись не найдена.")
    return Response(status_code=204)
