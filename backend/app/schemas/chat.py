from __future__ import annotations
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field
from app.models import ChatRoomType


class ChatRoomCreate(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    room_type: ChatRoomType = ChatRoomType.group_general
    group_id: UUID | None = None
    recipe_id: UUID | None = None


class ChatRoomOut(BaseModel):
    id: UUID
    name: str | None
    room_type: ChatRoomType
    group_id: UUID | None
    created_at: datetime
    model_config = {"from_attributes": True}


class ChatMessageOut(BaseModel):
    id: UUID
    room_id: UUID
    sender_id: UUID
    sender_username: str
    sender_display_name: str | None
    recipe_id: UUID | None
    body: str
    sent_at: datetime
    edited_at: datetime | None
    model_config = {"from_attributes": True}


class WSMessageIn(BaseModel):
    """Payload the client sends over the WebSocket."""
    type: str           # "message" | "typing" | "ping"
    body: str | None = None
    recipe_id: UUID | None = None


class WSMessageOut(BaseModel):
    """Payload the server broadcasts over the WebSocket."""
    type: str           # "message" | "typing" | "presence" | "pong" | "error"
    room_id: UUID | None = None
    sender_id: UUID | None = None
    sender_username: str | None = None
    body: str | None = None
    recipe_id: UUID | None = None
    message_id: UUID | None = None
    sent_at: datetime | None = None
