from typing import Optional
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
    co: Optional[float]
    no: Optional[float]
    no2: Optional[float]
    o3: Optional[float]
    so2: Optional[float]
    pm2_5: Optional[float]
    pm10: Optional[float]
    nh3: Optional[float]
    aqi: Optional[int]
    is_anomaly: bool
