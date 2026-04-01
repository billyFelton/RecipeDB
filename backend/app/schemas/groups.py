from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from app.models import GroupRole


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    is_public: bool = False


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    is_public: bool | None = None


class GroupOut(BaseModel):
    id: UUID
    name: str
    description: str | None
    owner_id: UUID
    invite_code: str
    is_public: bool
    created_at: datetime
    member_count: int = 0

    model_config = {"from_attributes": True}


class GroupMemberOut(BaseModel):
    user_id: UUID
    username: str
    display_name: str | None
    avatar_url: str | None
    role: GroupRole
    joined_at: datetime

    model_config = {"from_attributes": True}


class InviteResponse(BaseModel):
    invite_code: str
    invite_url: str


class JoinByCodeRequest(BaseModel):
    invite_code: str


class UpdateMemberRoleRequest(BaseModel):
    role: GroupRole
