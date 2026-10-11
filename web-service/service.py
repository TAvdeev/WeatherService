"""Отдельный адаптер официального API Open-Meteo. Базы данных здесь нет."""
import logging
import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="Погода и климат — погодный веб-сервис", version="1.0.0")
log = logging.getLogger(__name__)
GEO = os.getenv("GEOCODING_URL", "https://geocoding-api.open-meteo.com/v1")
WEATHER = os.getenv("WEATHER_URL", "https://api.open-meteo.com/v1/forecast")

DESCRIPTIONS = {
    0: "Ясно", 1: "Преимущественно ясно", 2: "Переменная облачность", 3: "Пасмурно",
    45: "Туман", 48: "Изморозевый туман", 51: "Слабая морось", 53: "Морось",
    55: "Сильная морось", 56: "Слабая ледяная морось", 57: "Ледяная морось",
    61: "Слабый дождь", 63: "Дождь", 65: "Сильный дождь", 66: "Слабый ледяной дождь",
    67: "Ледяной дождь", 71: "Слабый снег", 73: "Снег", 75: "Сильный снег",
    77: "Снежные зёрна", 80: "Слабый ливень", 81: "Ливень", 82: "Сильный ливень",
    85: "Слабый снежный ливень", 86: "Сильный снежный ливень", 95: "Гроза",
    96: "Гроза с небольшим градом", 99: "Гроза с сильным градом",
}


def request_json(url: str, params: dict) -> dict:
    try:
        with httpx.Client(timeout=httpx.Timeout(10, connect=4)) as client:
            response = client.get(url, params=params)
        if response.status_code == 429:
            raise HTTPException(503, "Open-Meteo ограничил частоту запросов. Попробуйте позже.")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Unexpected provider payload")
        return payload
    except httpx.TimeoutException as exc:
        raise HTTPException(504, "Open-Meteo не ответил вовремя. Повторите запрос позже.") from exc
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("Weather provider error: %s", type(exc).__name__)
        raise HTTPException(502, "Не удалось получить корректный ответ Open-Meteo.") from exc


def clean_city(city: str) -> str:
    city = city.strip()
    if not 2 <= len(city) <= 100:
        raise HTTPException(422, "Введите название города длиной от 2 до 100 символов.")
    return city


def location_view(item: dict) -> dict:
    return {"id": int(item["id"]), "name": item["name"], "country": item.get("country", ""),
            "region": item.get("admin1", ""), "latitude": item["latitude"],
            "longitude": item["longitude"]}


@app.get("/health", tags=["Состояние"])
def health():
    # Доступность провайдера не должна мешать запуску и чтению истории без интернета.
    return {"status": "ok", "service": "web-service"}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home():
    return """<!doctype html><html lang="ru"><meta charset="utf-8"><title>Погодный сервис</title>
    <body style="font:18px system-ui;max-width:800px;margin:60px auto;padding:20px">
    <h1>Погодный веб-сервис</h1><p>Отдельный контейнер адаптирует официальный API
    <a href="https://open-meteo.com/">Open-Meteo</a>: название города → координаты → текущая погода.</p>
    <p>Условия основаны на погодных моделях; это не прямое измерение метеостанции.</p>
    <p>Географические данные: <a href="https://www.geonames.org/">GeoNames</a>.</p>
    <a href="/docs">Открыть интерактивную документацию API</a> · <a href="/health">Проверить состояние</a>
    <p>Пример: <a href="/weather?city=Moscow">/weather?city=Moscow</a></p></body></html>"""


@app.get("/cities", tags=["Погода"])
def cities(q: str = Query(min_length=2, max_length=100)):
    data = request_json(f"{GEO}/search", {"name": clean_city(q), "count": 8, "language": "ru", "format": "json"})
    try:
        return {"items": [location_view(item) for item in data.get("results", [])]}
    except (TypeError, KeyError, ValueError) as exc:
        raise HTTPException(502, "Некорректный список городов от Open-Meteo.") from exc


@app.get("/weather", tags=["Погода"])
def weather(city: str = Query(min_length=2, max_length=100), location_id: int | None = Query(None, gt=0)):
    city = clean_city(city)
    if location_id:
        data = request_json(f"{GEO}/get", {"id": location_id, "language": "ru"})
        # /get with a single id returns a location object, not a search result list.
        if "id" not in data:
            raise HTTPException(404, "Город не найден.")
        location = data
    else:
        results = request_json(f"{GEO}/search", {"name": city, "count": 1, "language": "ru"}).get("results", [])
        if not results:
            raise HTTPException(404, "Город не найден. Проверьте название или введите его латиницей.")
        location = results[0]
    try:
        place = location_view(location)
        data = request_json(WEATHER, {
            "latitude": place["latitude"], "longitude": place["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            "temperature_unit": "celsius", "wind_speed_unit": "ms", "timeformat": "unixtime", "timezone": "GMT",
        })
        current = data["current"]
        code = int(current["weather_code"])
        return {
            "requested_city": city, "city": place["name"], "country": place["country"],
            "region": place["region"], "latitude": float(place["latitude"]), "longitude": float(place["longitude"]),
            "temperature": float(current["temperature_2m"]), "feels_like": float(current["apparent_temperature"]),
            "humidity": int(current["relative_humidity_2m"]), "wind_speed": float(current["wind_speed_10m"]),
            "weather_code": code, "description": DESCRIPTIONS.get(code, "Неизвестные погодные условия"),
            "observed_at": datetime.fromtimestamp(current["time"], timezone.utc).isoformat(),
            "source": "Open-Meteo", "source_url": "https://open-meteo.com/",
        }
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(502, "В ответе Open-Meteo отсутствуют корректные погодные данные.") from exc
