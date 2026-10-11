BEGIN;
CREATE TABLE weather_requests (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    requested_city VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL,
    country VARCHAR(100) NOT NULL,
    region VARCHAR(150) NOT NULL DEFAULT '',
    latitude DOUBLE PRECISION NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude DOUBLE PRECISION NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    temperature DOUBLE PRECISION NOT NULL,
    feels_like DOUBLE PRECISION NOT NULL,
    humidity INTEGER NOT NULL CHECK (humidity BETWEEN 0 AND 100),
    wind_speed DOUBLE PRECISION NOT NULL CHECK (wind_speed >= 0),
    weather_code INTEGER NOT NULL,
    description VARCHAR(100) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source VARCHAR(100) NOT NULL DEFAULT 'Open-Meteo',
    source_url TEXT NOT NULL DEFAULT 'https://open-meteo.com/',
    note VARCHAR(500) NOT NULL DEFAULT '',
    is_demo BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX weather_requests_date_idx ON weather_requests (requested_at DESC, id DESC);
CREATE INDEX weather_requests_city_idx ON weather_requests (city);
-- Это учебные примеры, а не реальные измерения или ответы API.
INSERT INTO weather_requests
 (requested_city, city, country, latitude, longitude, temperature, feels_like,
  humidity, wind_speed, weather_code, description, observed_at, requested_at, source, note, is_demo)
VALUES
 ('Москва', 'Москва', 'Россия', 55.7522, 37.6156, 12, 10, 68, 3.2, 3, 'Пасмурно',
  '2026-09-01 09:00:00+00', '2026-09-01 09:01:00+00', 'Учебный пример', 'Начальная запись для демонстрации БД', TRUE),
 ('Казань', 'Казань', 'Россия', 55.7887, 49.1221, 15, 14, 55, 2.1, 1, 'Преимущественно ясно',
  '2026-09-01 10:00:00+00', '2026-09-01 10:01:00+00', 'Учебный пример', 'Эти значения не получены от погодного API', TRUE);
COMMIT;
