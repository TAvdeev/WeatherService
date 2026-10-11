"""Детерминированные проверки API и ошибок провайдера; интернет и Docker не нужны."""
import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import main as backend

spec = importlib.util.spec_from_file_location("weather_service", ROOT / "web-service/service.py")
service = importlib.util.module_from_spec(spec)
spec.loader.exec_module(service)

PLACE = {"id": 524901, "name": "Москва", "country": "Россия", "admin1": "Москва", "latitude": 55.75, "longitude": 37.62}
CURRENT = {"current": {"time": 1791723600, "temperature_2m": 8.5, "apparent_temperature": 6.2,
                       "relative_humidity_2m": 72, "wind_speed_10m": 3.1, "weather_code": 3}}


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(service.app)

    def test_health_independent_from_internet(self):
        with patch.object(service, "request_json", side_effect=AssertionError("Unexpected network")):
            self.assertEqual(self.client.get("/health").status_code, 200)

    def test_city_disambiguation(self):
        with patch.object(service, "request_json", return_value={"results": [PLACE, {**PLACE, "id": 2, "country": "США"}]}):
            items = self.client.get("/cities?q=Москва").json()["items"]
            self.assertEqual(len(items), 2)
            self.assertEqual(items[1]["country"], "США")

    def test_selected_location_and_units(self):
        with patch.object(service, "request_json", side_effect=[PLACE, CURRENT]) as upstream:
            response = self.client.get("/weather?city=Москва&location_id=524901")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["humidity"], 72)
            self.assertTrue(response.json()["observed_at"].endswith("+00:00"))
            self.assertEqual(upstream.call_args.args[1]["wind_speed_unit"], "ms")
            self.assertEqual(upstream.call_args_list[0].args[0], f"{service.GEO}/get")

    def test_not_found(self):
        with patch.object(service, "request_json", return_value={}):
            self.assertEqual(self.client.get("/weather?city=Несуществующий").status_code, 404)

    def test_missing_weather_is_error(self):
        with patch.object(service, "request_json", side_effect=[PLACE, {"current": {}}]):
            self.assertEqual(self.client.get("/weather?city=Москва&location_id=1").status_code, 502)

    def test_blank_city(self):
        self.assertEqual(self.client.get("/weather", params={"city": "  "}).status_code, 422)

    def test_invalid_location_id(self):
        self.assertEqual(self.client.get("/weather?city=Москва&location_id=-1").status_code, 422)

    def test_timeout_becomes_504(self):
        with patch.object(service.httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.side_effect = httpx.ReadTimeout("Timeout")
            self.assertEqual(self.client.get("/cities?q=Москва").status_code, 504)

    def test_rate_limit_becomes_503(self):
        response = httpx.Response(429, request=httpx.Request("GET", "https://example.test"))
        with patch.object(service.httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.return_value = response
            self.assertEqual(self.client.get("/cities?q=Москва").status_code, 503)

    def test_malformed_json_becomes_502(self):
        response = httpx.Response(200, text="not json", request=httpx.Request("GET", "https://example.test"))
        with patch.object(service.httpx, "Client") as client:
            client.return_value.__enter__.return_value.get.return_value = response
            self.assertEqual(self.client.get("/cities?q=Москва").status_code, 502)


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(backend.app)

    def test_provider_failure_never_creates_record(self):
        with patch.object(backend, "service_get", side_effect=HTTPException(504, "Timeout")), patch.object(backend, "connect") as database:
            self.assertEqual(self.client.post("/api/weather", json={"city": "Москва"}).status_code, 504)
            database.assert_not_called()

    def test_bad_payload_never_creates_record(self):
        with patch.object(backend, "service_get", return_value={"temperature": 8}), patch.object(backend, "connect") as database:
            self.assertEqual(self.client.post("/api/weather", json={"city": "Москва"}).status_code, 502)
            database.assert_not_called()

    def test_database_outage_is_503(self):
        with patch.object(backend, "connect", side_effect=backend.psycopg.OperationalError("test")):
            response = self.client.get("/api/history")
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("password", response.text)

    def test_blank_city_rejected(self):
        self.assertEqual(self.client.post("/api/weather", json={"city": "  "}).status_code, 422)

    def test_note_limit(self):
        self.assertEqual(self.client.patch("/api/history/1", json={"note": "x" * 501}).status_code, 422)

    def test_pagination_limits(self):
        for suffix in ["limit=0", "limit=101", "offset=-1"]:
            self.assertEqual(self.client.get(f"/api/history?{suffix}").status_code, 422)

    def test_api_docs(self):
        self.assertEqual(self.client.get("/docs").status_code, 200)
        self.assertIn("/api/weather", self.client.get("/openapi.json").json()["paths"])


if __name__ == "__main__":
    unittest.main()
