from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Group, GroupMember, GroupRole, User
from app.schemas.groups import (
    GroupCreate, GroupMemberOut, GroupOut, GroupUpdate,
    InviteResponse, UpdateMemberRoleRequest,
)

router = APIRouter(prefix="/groups", tags=["groups"])

async def _get_group_or_404(db, group_id):
    result = await db.execute(select(Group).where(Group.id == group_id))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return group

async def _get_membership(db, group_id, user_id):
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
    )
    return result.scalar_one_or_none()

async def _require_membership(db, group_id, user_id):
    m = await _get_membership(db, group_id, user_id)
    if not m:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a group member")
    return m

async def _require_admin(db, group_id, user_id):
    m = await _require_membership(db, group_id, user_id)
    if m.role not in (GroupRole.owner, GroupRole.admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return m

async def _require_owner(db, group_id, user_id):
    m = await _require_membership(db, group_id, user_id)
    if m.role != GroupRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner access required")
    return m

async def _member_count(db, group_id):
    result = await db.execute(select(func.count()).where(GroupMember.group_id == group_id))
    return result.scalar_one()

async def _enrich(group, db):
    count = await _member_count(db, group.id)
    out = GroupOut.model_validate(group)
    out.member_count = count
    return out


@router.get("", response_model=list[GroupOut])
async def list_my_groups(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Group).join(GroupMember, GroupMember.group_id == Group.id)
        .where(GroupMember.user_id == current_user.id).order_by(Group.name)
    )
    return [await _enrich(g, db) for g in result.scalars().all()]


@router.post("", response_model=GroupOut, status_code=status.HTTP_201_CREATED)
async def create_group(body: GroupCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group = Group(name=body.name, description=body.description, owner_id=current_user.id, is_public=body.is_public)
    db.add(group)
    await db.flush()
    db.add(GroupMember(group_id=group.id, user_id=current_user.id, role=GroupRole.owner))
    await db.flush()
    return await _enrich(group, db)


@router.get("/{group_id}", response_model=GroupOut)
async def get_group(group_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, group_id)
    if not group.is_public:
        await _require_membership(db, group_id, current_user.id)
    return await _enrich(group, db)


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(group_id: UUID, body: GroupUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, group_id)
    await _require_admin(db, group_id, current_user.id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.flush()
    return await _enrich(group, db)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, group_id)
    await _require_owner(db, group_id, current_user.id)
    await db.delete(group)


@router.get("/{group_id}/members", response_model=list[GroupMemberOut])
async def list_members(group_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_group_or_404(db, group_id)
    await _require_membership(db, group_id, current_user.id)
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id)
        .options(selectinload(GroupMember.user)).order_by(GroupMember.joined_at)
    )
    return [
        GroupMemberOut(user_id=m.user_id, username=m.user.username, display_name=m.user.display_name,
                       avatar_url=m.user.avatar_url, role=m.role, joined_at=m.joined_at)
        for m in result.scalars().all()
    ]


@router.patch("/{group_id}/members/{user_id}", response_model=GroupMemberOut)
async def update_member_role(group_id: UUID, user_id: UUID, body: UpdateMemberRoleRequest,
                              current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_group_or_404(db, group_id)
    await _require_owner(db, group_id, current_user.id)
    if user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")
    if body.role == GroupRole.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Use transfer-ownership endpoint")
    membership = await _get_membership(db, group_id, user_id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    membership.role = body.role
    await db.flush()
    result = await db.execute(
        select(GroupMember).where(GroupMember.group_id == group_id, GroupMember.user_id == user_id)
        .options(selectinload(GroupMember.user))
    )
    m = result.scalar_one()
    return GroupMemberOut(user_id=m.user_id, username=m.user.username, display_name=m.user.display_name,
                          avatar_url=m.user.avatar_url, role=m.role, joined_at=m.joined_at)


@router.delete("/{group_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(group_id: UUID, user_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_group_or_404(db, group_id)
    if user_id != current_user.id:
        await _require_admin(db, group_id, current_user.id)
    membership = await _get_membership(db, group_id, user_id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    if membership.role == GroupRole.owner:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Transfer ownership before leaving")
    await db.delete(membership)


@router.get("/{group_id}/invite", response_model=InviteResponse)
async def get_invite(group_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, group_id)
    await _require_admin(db, group_id, current_user.id)
    return InviteResponse(invite_code=group.invite_code, invite_url=f"/api/v1/groups/join/{group.invite_code}")


@router.post("/{group_id}/invite/regenerate", response_model=InviteResponse)
async def regenerate_invite(group_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, group_id)
    await _require_admin(db, group_id, current_user.id)
    import secrets
    group.invite_code = secrets.token_hex(6)
    await db.flush()
    return InviteResponse(invite_code=group.invite_code, invite_url=f"/api/v1/groups/join/{group.invite_code}")


@router.post("/join/{invite_code}", response_model=GroupOut)
async def join_by_invite(invite_code: str, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Group).where(Group.invite_code == invite_code))
    group = result.scalar_one_or_none()
    if not group:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invalid invite code")
    if await _get_membership(db, group.id, current_user.id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already a member")
    db.add(GroupMember(group_id=group.id, user_id=current_user.id, role=GroupRole.member))
    await db.flush()
    return await _enrich(group, db)


@router.post("/{group_id}/transfer-ownership/{new_owner_id}", response_model=GroupOut)
async def transfer_ownership(group_id: UUID, new_owner_id: UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    group = await _get_group_or_404(db, group_id)
    await _require_owner(db, group_id, current_user.id)
    new_owner_membership = await _get_membership(db, group_id, new_owner_id)
    if not new_owner_membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="New owner must already be a member")
    current_membership = await _get_membership(db, group_id, current_user.id)
    current_membership.role = GroupRole.admin
    new_owner_membership.role = GroupRole.owner
    group.owner_id = new_owner_id
    await db.flush()
    return await _enrich(group, db)
