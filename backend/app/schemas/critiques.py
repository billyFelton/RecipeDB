from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from app.schemas.auth import UserPublic


class RatingCreate(BaseModel):
    score: int = Field(ge=1, le=5)


class RatingOut(BaseModel):
    id: UUID
    recipe_id: UUID
    user_id: UUID
    score: int
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


class RatingSummary(BaseModel):
    avg_rating: float | None
    rating_count: int
    user_score: int | None = None  # current user's own rating if any


class CritiqueCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    parent_id: UUID | None = None


class CritiqueUpdate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class CritiqueOut(BaseModel):
    id: UUID
    recipe_id: UUID
    user_id: UUID
    parent_id: UUID | None
    body: str
    upvotes: int
    created_at: datetime
    updated_at: datetime
    author: UserPublic
    has_upvoted: bool = False
    reply_count: int = 0
    model_config = {"from_attributes": True}
