from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from datetime import datetime

from app.database import get_db
from app.dependencies import get_current_user
from app.models import DeviceToken, Notification, NotificationType, User

router = APIRouter(tags=["notifications"])


# ---------------------------------------------------------------------------
# Schemas (small enough to live here)
# ---------------------------------------------------------------------------

class NotificationOut(BaseModel):
    id: UUID
    type: NotificationType
    payload: dict
    read: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class DeviceTokenRegister(BaseModel):
    token: str
    platform: str = "ios"


# ---------------------------------------------------------------------------
# Device token registration
# ---------------------------------------------------------------------------

@router.post("/devices/register", status_code=status.HTTP_204_NO_CONTENT)
async def register_device(
    body: DeviceTokenRegister,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Register or refresh an APNs device token for the current user."""
    result = await db.execute(
        select(DeviceToken).where(DeviceToken.token == body.token)
    )
    existing = result.scalar_one_or_none()

    if existing:
        # Re-associate with current user (device may have changed owner)
        existing.user_id = current_user.id
        existing.is_active = True
    else:
        db.add(DeviceToken(
            user_id=current_user.id,
            token=body.token,
            platform=body.platform,
        ))


@router.delete("/devices/{token}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_device(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deactivate a device token on logout."""
    result = await db.execute(
        select(DeviceToken).where(
            DeviceToken.token == token,
            DeviceToken.user_id == current_user.id,
        )
    )
    device = result.scalar_one_or_none()
    if device:
        device.is_active = False


# ---------------------------------------------------------------------------
# Notifications inbox
# ---------------------------------------------------------------------------

@router.get("/notifications", response_model=list[NotificationOut])
async def list_notifications(
    unread_only: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = [Notification.user_id == current_user.id]
    if unread_only:
        filters.append(Notification.read == False)

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Notification)
        .where(*filters)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    return result.scalars().all()


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == current_user.id,
        )
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    notif.read = True


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
async def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await db.execute(
        update(Notification)
        .where(Notification.user_id == current_user.id, Notification.read == False)
        .values(read=True)
    )


@router.get("/notifications/unread-count")
async def unread_count(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).where(
            Notification.user_id == current_user.id,
            Notification.read == False,
        )
    )
    return {"count": result.scalar_one()}
