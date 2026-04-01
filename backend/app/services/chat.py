"""
WebSocket connection manager with Redis Pub/Sub.

Each chat room maps to a Redis channel: chat:room:{room_id}
When a message is published to the channel, all API instances
that have subscribers in that room will broadcast it to their
connected WebSocket clients.
"""
import json
import asyncio
from uuid import UUID
from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.redis_client import get_redis


class ConnectionManager:
    def __init__(self):
        # room_id -> set of (user_id, WebSocket)
        self._rooms: dict[str, set[tuple[str, WebSocket]]] = {}

    def _channel(self, room_id: UUID) -> str:
        return f"chat:room:{room_id}"

    async def connect(self, room_id: UUID, user_id: UUID, websocket: WebSocket):
        await websocket.accept()
        key = str(room_id)
        if key not in self._rooms:
            self._rooms[key] = set()
        self._rooms[key].add((str(user_id), websocket))

    def disconnect(self, room_id: UUID, user_id: UUID, websocket: WebSocket):
        key = str(room_id)
        self._rooms.get(key, set()).discard((str(user_id), websocket))
        if not self._rooms.get(key):
            self._rooms.pop(key, None)

    async def broadcast_local(self, room_id: UUID, payload: dict):
        """Send to all local WebSocket connections in a room."""
        key = str(room_id)
        data = json.dumps(payload, default=str)
        dead: set[tuple[str, WebSocket]] = set()
        for uid, ws in list(self._rooms.get(key, set())):
            try:
                await ws.send_text(data)
            except Exception:
                dead.add((uid, ws))
        for entry in dead:
            self._rooms.get(key, set()).discard(entry)

    async def publish(self, room_id: UUID, payload: dict):
        """Publish to Redis so ALL API instances broadcast it."""
        redis = await get_redis()
        await redis.publish(self._channel(room_id), json.dumps(payload, default=str))

    async def subscribe(self, room_id: UUID):
        """
        Subscribe to a room's Redis channel and broadcast
        incoming messages to local WebSocket connections.
        Runs as a background task per room per API instance.
        """
        redis: aioredis.Redis = await get_redis()
        pubsub = redis.pubsub()
        await pubsub.subscribe(self._channel(room_id))
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    payload = json.loads(message["data"])
                    await self.broadcast_local(room_id, payload)
        finally:
            await pubsub.unsubscribe(self._channel(room_id))
            await pubsub.aclose()


manager = ConnectionManager()
