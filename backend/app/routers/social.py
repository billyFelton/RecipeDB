from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, or_, exists
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    Follow, GroupMember, Recipe, RecipeShare, RecipeTag,
    RecipeVisibility, User,
)
from app.schemas.auth import UserPublic
from app.schemas.recipes import RecipeSummary
from app.schemas.social import FeedItem, FollowerOut, FollowOut, UserProfileOut

router = APIRouter(tags=["social"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_user_or_404(db: AsyncSession, user_id: UUID) -> User:
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def _follower_count(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(select(func.count()).where(Follow.following_id == user_id))
    return result.scalar_one()


async def _following_count(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(select(func.count()).where(Follow.follower_id == user_id))
    return result.scalar_one()


async def _recipe_count(db: AsyncSession, user_id: UUID) -> int:
    result = await db.execute(select(func.count()).where(Recipe.author_id == user_id))
    return result.scalar_one()


async def _is_following(db: AsyncSession, follower_id: UUID, following_id: UUID) -> bool:
    result = await db.execute(
        select(func.count()).where(
            Follow.follower_id == follower_id,
            Follow.following_id == following_id,
        )
    )
    return result.scalar_one() > 0


async def _build_profile(
    db: AsyncSession, user: User, current_user: User
) -> UserProfileOut:
    return UserProfileOut(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        bio=user.bio,
        created_at=user.created_at,
        follower_count=await _follower_count(db, user.id),
        following_count=await _following_count(db, user.id),
        recipe_count=await _recipe_count(db, user.id),
        is_following=await _is_following(db, current_user.id, user.id),
    )


# ---------------------------------------------------------------------------
# User profiles
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}", response_model=UserProfileOut)
async def get_user_profile(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user = await _get_user_or_404(db, user_id)
    return await _build_profile(db, user, current_user)


@router.get("/users/by-username/{username}", response_model=UserProfileOut)
async def get_profile_by_username(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(User).where(User.username == username.lower(), User.is_active == True)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await _build_profile(db, user, current_user)


@router.get("/users/search", response_model=list[UserPublic])
async def search_users(
    q: str = Query(min_length=2),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User)
        .where(
            User.is_active == True,
            User.id != current_user.id,
            or_(
                User.username.ilike(f"%{q}%"),
                User.display_name.ilike(f"%{q}%"),
            ),
        )
        .order_by(User.username)
        .offset(offset)
        .limit(page_size)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Follow / unfollow
# ---------------------------------------------------------------------------

@router.post("/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def follow_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot follow yourself",
        )

    await _get_user_or_404(db, user_id)

    if await _is_following(db, current_user.id, user_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already following this user",
        )

    db.add(Follow(follower_id=current_user.id, following_id=user_id))


@router.delete("/users/{user_id}/follow", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Follow).where(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id,
        )
    )
    follow = result.scalar_one_or_none()
    if not follow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not following this user",
        )
    await db.delete(follow)


# ---------------------------------------------------------------------------
# Followers / following lists
# ---------------------------------------------------------------------------

@router.get("/users/{user_id}/followers", response_model=list[UserPublic])
async def list_followers(
    user_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_user_or_404(db, user_id)
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User)
        .join(Follow, Follow.follower_id == User.id)
        .where(Follow.following_id == user_id)
        .order_by(Follow.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    return result.scalars().all()


@router.get("/users/{user_id}/following", response_model=list[UserPublic])
async def list_following(
    user_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_user_or_404(db, user_id)
    offset = (page - 1) * page_size
    result = await db.execute(
        select(User)
        .join(Follow, Follow.following_id == User.id)
        .where(Follow.follower_id == user_id)
        .order_by(Follow.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Social feed
# ---------------------------------------------------------------------------

@router.get("/feed", response_model=list[FeedItem])
async def get_feed(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns recipes created or shared by users the current user follows,
    ordered by most recent activity. Respects recipe visibility rules.
    """
    # IDs of people the current user follows
    following_ids = select(Follow.following_id).where(Follow.follower_id == current_user.id)

    # Groups the current user belongs to
    user_group_ids = select(GroupMember.group_id).where(GroupMember.user_id == current_user.id)

    # Recipes authored by followed users that are visible
    authored = (
        select(Recipe, User, Recipe.created_at.label("activity_ts"))
        .join(User, User.id == Recipe.author_id)
        .where(
            Recipe.author_id.in_(following_ids),
            or_(
                Recipe.visibility == RecipeVisibility.public,
                and_(
                    Recipe.visibility == RecipeVisibility.group,
                    Recipe.group_id.in_(user_group_ids),
                ),
                Recipe.author_id == current_user.id,
            ),
        )
    )

    # Recipes shared by followed users
    shared = (
        select(Recipe, User, RecipeShare.shared_at.label("activity_ts"))
        .join(RecipeShare, RecipeShare.recipe_id == Recipe.id)
        .join(User, User.id == RecipeShare.shared_by)
        .where(
            RecipeShare.shared_by.in_(following_ids),
            or_(
                RecipeShare.target_user_id == current_user.id,
                RecipeShare.target_group_id.in_(user_group_ids),
            ),
        )
    )

    offset = (page - 1) * page_size

    # Fetch both sets and merge in Python (simple approach without UNION)
    authored_result = await db.execute(
        authored.options(selectinload(Recipe.tags), selectinload(Recipe.media))
        .order_by(Recipe.created_at.desc())
        .limit(page_size * 2)
    )
    shared_result = await db.execute(
        shared.options(selectinload(Recipe.tags), selectinload(Recipe.media))
        .order_by(RecipeShare.shared_at.desc())
        .limit(page_size * 2)
    )

    feed_items: list[FeedItem] = []

    for row in authored_result.all():
        recipe, actor, ts = row
        feed_items.append(FeedItem(
            recipe=RecipeSummary.model_validate(recipe),
            actor=UserPublic.model_validate(actor),
            action="created",
            timestamp=ts,
        ))

    for row in shared_result.all():
        recipe, actor, ts = row
        feed_items.append(FeedItem(
            recipe=RecipeSummary.model_validate(recipe),
            actor=UserPublic.model_validate(actor),
            action="shared",
            timestamp=ts,
        ))

    # Sort merged results and paginate
    feed_items.sort(key=lambda x: x.timestamp, reverse=True)
    return feed_items[offset: offset + page_size]


# ---------------------------------------------------------------------------
# Share a recipe
# ---------------------------------------------------------------------------

@router.post("/recipes/{recipe_id}/share", status_code=status.HTTP_204_NO_CONTENT)
async def share_recipe(
    recipe_id: UUID,
    target_user_id: UUID | None = None,
    target_group_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not target_user_id and not target_group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either target_user_id or target_group_id",
        )
    if target_user_id and target_group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide only one of target_user_id or target_group_id",
        )

    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")

    # Must be author or have visibility access to share
    if recipe.author_id != current_user.id and recipe.visibility == RecipeVisibility.private:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot share this recipe")

    db.add(RecipeShare(
        recipe_id=recipe_id,
        shared_by=current_user.id,
        target_user_id=target_user_id,
        target_group_id=target_group_id,
    ))
