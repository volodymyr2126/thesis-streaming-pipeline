from pydantic import BaseModel


class SensorReading(BaseModel):
    reading_id: str
    sensor_id: str
    station_name: str
    city: str
    region: str
    country: str
    latitude: float
    longitude: float
    timestamp: str
    co: float | None
    no: float | None
    no2: float | None
    o3: float | None
    so2: float | None
    pm2_5: float | None
    pm10: float | None
    nh3: float | None
    aqi: int | None
    is_anomaly: bool
