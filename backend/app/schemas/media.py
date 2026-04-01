from __future__ import annotations
from uuid import UUID
from pydantic import BaseModel


class MediaUploadOut(BaseModel):
    id: UUID
    url: str
    media_type: str
    is_cover: bool
    sort_order: int
    model_config = {"from_attributes": True}


class PresignedUploadOut(BaseModel):
    presigned_url: str
    final_url: str
    expires_in: int = 300


class MediaReorderItem(BaseModel):
    media_id: UUID
    sort_order: int


class SetCoverRequest(BaseModel):
    media_id: UUID
