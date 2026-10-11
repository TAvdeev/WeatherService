"""Проверка запущенного стека с настоящим Open-Meteo. Python 3, без pip.

python3 scripts/smoke.py [http://localhost:8080]
Создаёт одну реальную запись, проверяет CRUD, затем удаляет только её.
"""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")


def request(path, method="GET", body=None, expected=200):
    payload = None if body is None else json.dumps(body).encode()
    req = Request(BASE + path, data=payload, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, timeout=65) as response:
            assert response.status == expected, f"{path}: HTTP {response.status}"
            raw = response.read()
            return json.loads(raw) if raw else None
    except HTTPError as exc:
        if exc.code == expected:
            return None
        raise RuntimeError(f"{path}: HTTP {exc.code}: {exc.read().decode()}") from exc


def main():
    record_id = None
    try:
        with urlopen(BASE + "/", timeout=10) as response:
            assert response.status == 200 and "Погода и климат" in response.read().decode()
        history = request("/api/history?limit=1")
        assert isinstance(history["items"], list)
        cities = request("/api/cities?q=Moscow")
        assert cities["items"], "Провайдер не вернул города"
        record = request("/api/weather", "POST", {"city": "Moscow", "location_id": cities["items"][0]["id"]}, 201)
        record_id = record["id"]
        assert record["source"] == "Open-Meteo" and not record["is_demo"]
        assert request(f"/api/history/{record_id}")["id"] == record_id
        request(f"/api/history/{record_id}", "PATCH", {"note": "Проверка Docker Compose"})
        assert request(f"/api/history/{record_id}")["note"] == "Проверка Docker Compose"
        request(f"/api/history/{record_id}", "DELETE", expected=204)
        request(f"/api/history/{record_id}", expected=404)
        record_id = None
        print("УСПЕХ: Frontend → Backend → Web-сервис → Open-Meteo; запись, чтение, изменение и удаление в PostgreSQL.")
    finally:
        if record_id is not None:
            try:
                request(f"/api/history/{record_id}", "DELETE", expected=204)
            except Exception:
                print(f"Не удалось удалить проверочную запись № {record_id}. Её можно удалить в интерфейсе.", file=sys.stderr)


if __name__ == "__main__":
    try:
        main()
    except (URLError, TimeoutError, RuntimeError, AssertionError, KeyError, ValueError) as exc:
        print(f"ПРОВЕРКА НЕ ПРОЙДЕНА: {exc}", file=sys.stderr)
        sys.exit(1)
