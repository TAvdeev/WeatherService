"""Интеграционные проверки с настоящей БД. Запускать только на учебной БД.

WEATHER_TEST_DATABASE=1 python -m unittest discover -s tests -v
Параметры DB_* должны указывать на инициализированную базу приложения.
"""
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import main

SNAPSHOT = dict(requested_city="Тестовый город", city="Тестовый город", country="Россия", region="",
                latitude=55.75, longitude=37.62, temperature=8.5, feels_like=6.2, humidity=72,
                wind_speed=3.1, weather_code=3, description="Пасмурно", observed_at="2026-10-11T09:00:00+00:00",
                source="Open-Meteo", source_url="https://open-meteo.com/")


@unittest.skipUnless(os.getenv("WEATHER_TEST_DATABASE") == "1", "Требуется отдельная тестовая PostgreSQL")
class DatabaseTests(unittest.TestCase):
    def test_crud_filters_pagination_and_rollback(self):
        client = TestClient(main.app)
        ids = []
        try:
            self.assertEqual(client.get("/health").status_code, 200)
            with patch.object(main, "service_get", return_value=SNAPSHOT):
                for _ in range(2):
                    response = client.post("/api/weather", json={"city": "Тестовый город"})
                    self.assertEqual(response.status_code, 201, response.text)
                    ids.append(response.json()["id"])
            result = client.get("/api/history", params={"city": "Тестовый город", "limit": 1}).json()
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["items"][0]["id"], ids[1])
            self.assertEqual(client.get("/api/history", params={"city": "тестовый город"}).json()["total"], 2)
            second = client.get("/api/history", params={"city": "Тестовый город", "limit": 1, "offset": 1}).json()
            self.assertEqual(second["items"][0]["id"], ids[0])
            note = "Проверка ' кавычек; <script>alert(1)</script>"
            self.assertEqual(client.patch(f"/api/history/{ids[0]}", json={"note": note}).status_code, 200)
            self.assertEqual(client.get(f"/api/history/{ids[0]}").json()["note"], note)
            self.assertEqual(client.get("/api/history", params={"city": "%' OR 1=1 --"}).json()["total"], 0)
            self.assertEqual(client.get("/api/history", params={"city": "%"}).json()["total"], 0)
            self.assertEqual(client.delete(f"/api/history/{ids[0]}").status_code, 204)
            self.assertEqual(client.get(f"/api/history/{ids[0]}").status_code, 404)
            self.assertEqual(client.delete(f"/api/history/{ids[0]}").status_code, 404)
            self.assertEqual(client.patch(f"/api/history/{ids[0]}", json={"note":"test"}).status_code, 404)
        finally:
            for record_id in ids:
                client.delete(f"/api/history/{record_id}")


if __name__ == "__main__":
    unittest.main()
