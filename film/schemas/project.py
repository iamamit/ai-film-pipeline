import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    topic: str = Field(..., min_length=1, max_length=500)
    duration_minutes: int = Field(..., ge=1, le=60)
    tone: str | None = Field(None, max_length=50)
    style: str | None = Field(None, max_length=50)


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    topic: str
    duration_minutes: int
    tone: str | None
    status: str
    progress: int
    current_phase: str | None
    estimated_completion: datetime | None
    total_cost: Decimal
    created_at: datetime
    completed_at: datetime | None
    error_message: str | None


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    limit: int
    offset: int
