"""Data models for the producer service."""
from typing import Optional, List
from pydantic import BaseModel, Field, validator


class Event(BaseModel):
    """Event data model."""
    event_id: str
    timestamp: int  # Unix timestamp in milliseconds
    user_id: int
    event_type: str
    value: int
    metadata: Optional[dict] = None


class SimulateRequest(BaseModel):
    """Request model for /simulate endpoint."""
    rate: int = Field(default=10, ge=1, le=10000, description="Events per second")
    num_events: int = Field(default=100, ge=1, le=10000000, description="Total number of events to generate")
    event_types: Optional[List[str]] = Field(default=None, description="Event types to generate (null = all)")

    @validator('event_types')
    def validate_event_types(cls, v):
        if v is not None:
            from src.config import EVENT_TYPES
            for event_type in v:
                if event_type not in EVENT_TYPES:
                    raise ValueError(f"Invalid event_type: {event_type}. Must be one of {EVENT_TYPES}")
        return v


class SimulateResponse(BaseModel):
    """Response model for /simulate endpoint."""
    status: str
    message: str
    simulation_id: str
    rate: int
    num_events: int
    estimated_duration: float


class StatsResponse(BaseModel):
    """Response model for /stats endpoint."""
    status: str
    is_running: bool
    events_sent: int
    events_failed: int
    current_rate: float
    total_duration: float
    avg_latency_ms: float
