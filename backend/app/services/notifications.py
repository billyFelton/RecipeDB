"""
Notification service — creates DB notification records and fires APNs pushes.
Call these functions from routers after significant events.
"""
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DeviceToken, Notification, NotificationType, User
from app.services.apns import send_push_many

# Human-readable push copy per notification type
_PUSH_TEMPLATES: dict[NotificationType, tuple[str, str]] = {
    NotificationType.new_follower:    ("{actor} started following you", ""),
    NotificationType.recipe_shared:   ("{actor} shared a recipe with you", "{title}"),
    NotificationType.new_critique:    ("{actor} critiqued your recipe", "{title}"),
    NotificationType.critique_reply:  ("{actor} replied to your critique", "{body}"),
    NotificationType.critique_upvote: ("{actor} upvoted your critique", ""),
    NotificationType.new_rating:      ("{actor} rated your recipe", "{title}"),
    NotificationType.group_invite:    ("{actor} invited you to {group}", "Tap to join"),
    NotificationType.chat_mention:    ("{actor} mentioned you in {room}", "{body}"),
}


def _render(template: str, ctx: dict) -> str:
    try:
        return template.format(**ctx)
    except KeyError:
        return template


async def create_notification(
    db: AsyncSession,
    user_id: UUID,
    notification_type: NotificationType,
    payload: dict,
    push: bool = True,
) -> Notification:
    """
    Persist a notification record and optionally fire an APNs push.
    Always call inside an active db transaction (router handles commit).
    """
    notif = Notification(
        user_id=user_id,
        type=notification_type,
        payload=payload,
    )
    db.add(notif)
    await db.flush()

    if push:
        # Load device tokens for the target user
        tokens_result = await db.execute(
            select(DeviceToken).where(
                DeviceToken.user_id == user_id,
                DeviceToken.is_active == True,
            )
        )
        tokens = tokens_result.scalars().all()

        if tokens:
            title_tmpl, body_tmpl = _PUSH_TEMPLATES.get(
                notification_type, ("New notification", "")
            )
            title = _render(title_tmpl, payload)
            body = _render(body_tmpl, payload) if body_tmpl else ""

            await send_push_many([
                {
                    "device_token": t.token,
                    "title": title,
                    "body": body,
                    "data": {"type": notification_type.value, **payload},
                }
                for t in tokens
            ])

    return notif


# ---------------------------------------------------------------------------
# Convenience wrappers called from routers
# ---------------------------------------------------------------------------

async def notify_new_follower(db: AsyncSession, target_user_id: UUID, actor: User):
    await create_notification(db, target_user_id, NotificationType.new_follower, {
        "actor": actor.display_name or actor.username,
        "actor_id": str(actor.id),
    })


async def notify_recipe_shared(db: AsyncSession, target_user_id: UUID, actor: User, recipe_title: str, recipe_id: UUID):
    await create_notification(db, target_user_id, NotificationType.recipe_shared, {
        "actor": actor.display_name or actor.username,
        "actor_id": str(actor.id),
        "title": recipe_title,
        "recipe_id": str(recipe_id),
    })


async def notify_new_critique(db: AsyncSession, target_user_id: UUID, actor: User, recipe_title: str, recipe_id: UUID):
    await create_notification(db, target_user_id, NotificationType.new_critique, {
        "actor": actor.display_name or actor.username,
        "actor_id": str(actor.id),
        "title": recipe_title,
        "recipe_id": str(recipe_id),
    })


async def notify_critique_reply(db: AsyncSession, target_user_id: UUID, actor: User, body_preview: str, recipe_id: UUID):
    await create_notification(db, target_user_id, NotificationType.critique_reply, {
        "actor": actor.display_name or actor.username,
        "actor_id": str(actor.id),
        "body": body_preview[:80],
        "recipe_id": str(recipe_id),
    })


async def notify_new_rating(db: AsyncSession, target_user_id: UUID, actor: User, recipe_title: str, recipe_id: UUID):
    await create_notification(db, target_user_id, NotificationType.new_rating, {
        "actor": actor.display_name or actor.username,
        "actor_id": str(actor.id),
        "title": recipe_title,
        "recipe_id": str(recipe_id),
    })


async def notify_group_invite(db: AsyncSession, target_user_id: UUID, actor: User, group_name: str, group_id: UUID):
    await create_notification(db, target_user_id, NotificationType.group_invite, {
        "actor": actor.display_name or actor.username,
        "actor_id": str(actor.id),
        "group": group_name,
        "group_id": str(group_id),
    })


async def notify_chat_mention(db: AsyncSession, target_user_id: UUID, actor: User, room_name: str, body_preview: str, room_id: UUID):
    await create_notification(db, target_user_id, NotificationType.chat_mention, {
        "actor": actor.display_name or actor.username,
        "actor_id": str(actor.id),
        "room": room_name or "chat",
        "body": body_preview[:80],
        "room_id": str(room_id),
    })
