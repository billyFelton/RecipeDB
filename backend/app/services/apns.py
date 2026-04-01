"""
Apple Push Notification Service (APNs) — token-based auth (.p8 key).

Required environment variables:
  APNS_KEY_ID      — 10-char key ID from Apple Developer portal
  APNS_TEAM_ID     — 10-char Team ID from Apple Developer portal
  APNS_BUNDLE_ID   — your app bundle ID e.g. com.yourname.recipedb
  APNS_KEY_PATH    — path to the .p8 file inside the container
  APNS_PRODUCTION  — "true" for App Store / TestFlight, "false" for sandbox
"""
import json
import logging
from dataclasses import dataclass

import aioapns
from aioapns import APNs, NotificationRequest

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_apns_client: APNs | None = None


async def get_apns_client() -> APNs | None:
    """Lazy-initialise the APNs client. Returns None if APNs is not configured."""
    global _apns_client
    if _apns_client is not None:
        return _apns_client

    if not all([
        settings.apns_key_id,
        settings.apns_team_id,
        settings.apns_bundle_id,
        settings.apns_key_path,
    ]):
        logger.warning("APNs not configured — push notifications disabled")
        return None

    try:
        _apns_client = APNs(
            key=settings.apns_key_path,
            key_id=settings.apns_key_id,
            team_id=settings.apns_team_id,
            topic=settings.apns_bundle_id,
            use_sandbox=not settings.apns_production,
        )
        logger.info("APNs client initialised (sandbox=%s)", not settings.apns_production)
        return _apns_client
    except Exception as e:
        logger.error("Failed to initialise APNs client: %s", e)
        return None


async def send_push(
    device_token: str,
    title: str,
    body: str,
    data: dict | None = None,
    badge: int | None = None,
    sound: str = "default",
) -> bool:
    """
    Send a push notification to a single device.
    Returns True on success, False on failure.
    Swallows exceptions so a failed push never breaks the main request.
    """
    client = await get_apns_client()
    if not client:
        return False

    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": sound,
        }
    }
    if badge is not None:
        payload["aps"]["badge"] = badge
    if data:
        payload.update(data)

    try:
        request = NotificationRequest(
            device_token=device_token,
            message=payload,
        )
        result = await client.send_notification(request)
        if result.is_successful:
            return True
        logger.warning("APNs rejected push to %s: %s", device_token[:8], result.description)
        return False
    except Exception as e:
        logger.error("APNs send error: %s", e)
        return False


async def send_push_many(notifications: list[dict]) -> None:
    """
    Fire-and-forget batch push.
    Each item: {device_token, title, body, data, badge}
    """
    import asyncio
    tasks = [
        send_push(
            device_token=n["device_token"],
            title=n["title"],
            body=n["body"],
            data=n.get("data"),
            badge=n.get("badge"),
        )
        for n in notifications
    ]
    await asyncio.gather(*tasks, return_exceptions=True)
