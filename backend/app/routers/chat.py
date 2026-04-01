import asyncio
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, AsyncSessionLocal
from app.dependencies import get_current_user
from app.models import ChatMessage, ChatRoom, ChatRoomType, GroupMember, User
from app.schemas.chat import (
    ChatMessageOut, ChatRoomCreate, ChatRoomOut, WSMessageIn, WSMessageOut,
)
from app.services.auth import decode_access_token, get_user_by_id
from app.services.chat import manager

router = APIRouter(prefix="/chat", tags=["chat"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_room_or_404(db: AsyncSession, room_id: UUID) -> ChatRoom:
    result = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
    room = result.scalar_one_or_none()
    if not room:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Room not found")
    return room


async def _assert_room_access(db: AsyncSession, room: ChatRoom, user_id: UUID):
    """Group rooms require group membership. Direct rooms require membership record."""
    if room.group_id:
        result = await db.execute(
            select(GroupMember).where(
                GroupMember.group_id == room.group_id,
                GroupMember.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a group member")


def _message_out(msg: ChatMessage, sender: User) -> ChatMessageOut:
    return ChatMessageOut(
        id=msg.id,
        room_id=msg.room_id,
        sender_id=msg.sender_id,
        sender_username=sender.username,
        sender_display_name=sender.display_name,
        recipe_id=msg.recipe_id,
        body=msg.body,
        sent_at=msg.sent_at,
        edited_at=msg.edited_at,
    )


# ---------------------------------------------------------------------------
# REST: room management
# ---------------------------------------------------------------------------

@router.post("/rooms", response_model=ChatRoomOut, status_code=status.HTTP_201_CREATED)
async def create_room(
    body: ChatRoomCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if body.room_type == ChatRoomType.group_general and not body.group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="group_id required for group_general rooms",
        )

    room = ChatRoom(
        group_id=body.group_id,
        name=body.name,
        room_type=body.room_type,
    )
    db.add(room)
    await db.flush()
    await db.refresh(room)
    return room


@router.get("/rooms", response_model=list[ChatRoomOut])
async def list_my_rooms(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns all chat rooms accessible to the current user via group membership."""
    user_group_ids = select(GroupMember.group_id).where(GroupMember.user_id == current_user.id)
    result = await db.execute(
        select(ChatRoom).where(ChatRoom.group_id.in_(user_group_ids))
        .order_by(ChatRoom.created_at)
    )
    return result.scalars().all()


@router.get("/rooms/{room_id}", response_model=ChatRoomOut)
async def get_room(
    room_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room_or_404(db, room_id)
    await _assert_room_access(db, room, current_user.id)
    return room


# ---------------------------------------------------------------------------
# REST: message history
# ---------------------------------------------------------------------------

@router.get("/rooms/{room_id}/messages", response_model=list[ChatMessageOut])
async def get_message_history(
    room_id: UUID,
    before: datetime | None = Query(default=None),
    page_size: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    room = await _get_room_or_404(db, room_id)
    await _assert_room_access(db, room, current_user.id)

    filters = [ChatMessage.room_id == room_id]
    if before:
        filters.append(ChatMessage.sent_at < before)

    result = await db.execute(
        select(ChatMessage)
        .where(*filters)
        .options(selectinload(ChatMessage.room))
        .order_by(ChatMessage.sent_at.desc())
        .limit(page_size)
    )
    messages = result.scalars().all()

    # Load senders
    sender_ids = {m.sender_id for m in messages}
    senders_result = await db.execute(select(User).where(User.id.in_(sender_ids)))
    senders = {u.id: u for u in senders_result.scalars().all()}

    return [_message_out(m, senders[m.sender_id]) for m in reversed(messages)]


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/rooms/{room_id}/ws")
async def websocket_endpoint(
    room_id: UUID,
    websocket: WebSocket,
    token: str = Query(...),
):
    """
    Connect to a chat room via WebSocket.

    Authentication: pass the JWT access token as a query param:
      ws://host/api/v1/chat/rooms/{room_id}/ws?token=<access_token>

    Client message format (JSON):
      { "type": "message", "body": "Hello!", "recipe_id": null }
      { "type": "typing" }
      { "type": "ping" }

    Server message format (JSON):
      { "type": "message", "sender_id": "...", "body": "...", ... }
      { "type": "typing",  "sender_id": "...", "sender_username": "..." }
      { "type": "pong" }
      { "type": "error",  "body": "reason" }
    """
    # --- Auth via token query param (HTTP headers unavailable in WS upgrade) ---
    try:
        user_id = decode_access_token(token)
    except ValueError:
        await websocket.close(code=4001, reason="Invalid token")
        return

    async with AsyncSessionLocal() as db:
        user = await get_user_by_id(db, user_id)
        if not user or not user.is_active:
            await websocket.close(code=4001, reason="User not found")
            return

        try:
            room_result = await db.execute(select(ChatRoom).where(ChatRoom.id == room_id))
            room = room_result.scalar_one_or_none()
            if not room:
                await websocket.close(code=4004, reason="Room not found")
                return

            await _assert_room_access(db, room, user.id)
        except HTTPException:
            await websocket.close(code=4003, reason="Access denied")
            return

    # --- Connect and start Redis subscriber for this room ---
    await manager.connect(room_id, user.id, websocket)
    subscriber_task = asyncio.create_task(manager.subscribe(room_id))

    # Broadcast presence
    await manager.publish(room_id, WSMessageOut(
        type="presence",
        sender_id=user.id,
        sender_username=user.username,
        body="joined",
    ).model_dump())

    try:
        while True:
            raw = await websocket.receive_text()

            try:
                msg_in = WSMessageIn.model_validate_json(raw)
            except Exception:
                await websocket.send_text(json.dumps({"type": "error", "body": "Invalid message format"}))
                continue

            if msg_in.type == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
                continue

            if msg_in.type == "typing":
                await manager.publish(room_id, WSMessageOut(
                    type="typing",
                    sender_id=user.id,
                    sender_username=user.username,
                ).model_dump())
                continue

            if msg_in.type == "message":
                if not msg_in.body or not msg_in.body.strip():
                    await websocket.send_text(json.dumps({"type": "error", "body": "Empty message"}))
                    continue

                # Persist to database
                async with AsyncSessionLocal() as db:
                    chat_msg = ChatMessage(
                        room_id=room_id,
                        sender_id=user.id,
                        recipe_id=msg_in.recipe_id,
                        body=msg_in.body.strip(),
                    )
                    db.add(chat_msg)
                    await db.commit()
                    await db.refresh(chat_msg)

                # Broadcast to room via Redis
                await manager.publish(room_id, WSMessageOut(
                    type="message",
                    room_id=room_id,
                    sender_id=user.id,
                    sender_username=user.username,
                    body=chat_msg.body,
                    recipe_id=chat_msg.recipe_id,
                    message_id=chat_msg.id,
                    sent_at=chat_msg.sent_at,
                ).model_dump())

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(room_id, user.id, websocket)
        subscriber_task.cancel()

        # Broadcast departure
        try:
            await manager.publish(room_id, WSMessageOut(
                type="presence",
                sender_id=user.id,
                sender_username=user.username,
                body="left",
            ).model_dump())
        except Exception:
            pass
