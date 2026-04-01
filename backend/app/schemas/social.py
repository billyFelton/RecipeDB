from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from app.schemas.auth import UserPublic
from app.schemas.recipes import RecipeSummary


class FollowOut(BaseModel):
    following_id: UUID
    created_at: datetime
    model_config = {"from_attributes": True}


class FollowerOut(BaseModel):
    follower_id: UUID
    created_at: datetime
    model_config = {"from_attributes": True}


class UserProfileOut(UserPublic):
    follower_count: int = 0
    following_count: int = 0
    recipe_count: int = 0
    is_following: bool = False


class FeedItem(BaseModel):
    recipe: RecipeSummary
    actor: UserPublic
    action: str  # "created" | "shared"
    timestamp: datetime
