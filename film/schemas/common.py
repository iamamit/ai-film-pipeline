from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime


class ReadyResponse(BaseModel):
    status: str
    checks: dict[str, str]
