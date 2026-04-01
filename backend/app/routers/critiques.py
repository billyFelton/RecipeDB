from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, and_, delete
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Critique, CritiqueUpvote, Rating, Recipe, User
from app.schemas.critiques import (
    CritiqueCreate, CritiqueOut, CritiqueUpdate,
    RatingCreate, RatingOut, RatingSummary,
)
from app.schemas.auth import UserPublic

router = APIRouter(tags=["critiques"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_recipe_or_404(db: AsyncSession, recipe_id: UUID) -> Recipe:
    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return recipe


async def _get_critique_or_404(db: AsyncSession, critique_id: UUID) -> Critique:
    result = await db.execute(
        select(Critique)
        .where(Critique.id == critique_id)
        .options(selectinload(Critique.user))
    )
    critique = result.scalar_one_or_none()
    if not critique:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Critique not found")
    return critique


async def _has_upvoted(db: AsyncSession, critique_id: UUID, user_id: UUID) -> bool:
    result = await db.execute(
        select(func.count()).where(
            CritiqueUpvote.critique_id == critique_id,
            CritiqueUpvote.user_id == user_id,
        )
    )
    return result.scalar_one() > 0


async def _reply_count(db: AsyncSession, critique_id: UUID) -> int:
    result = await db.execute(
        select(func.count()).where(Critique.parent_id == critique_id)
    )
    return result.scalar_one()


async def _build_critique_out(
    db: AsyncSession, critique: Critique, current_user: User
) -> CritiqueOut:
    return CritiqueOut(
        id=critique.id,
        recipe_id=critique.recipe_id,
        user_id=critique.user_id,
        parent_id=critique.parent_id,
        body=critique.body,
        upvotes=critique.upvotes,
        created_at=critique.created_at,
        updated_at=critique.updated_at,
        author=UserPublic.model_validate(critique.user),
        has_upvoted=await _has_upvoted(db, critique.id, current_user.id),
        reply_count=await _reply_count(db, critique.id),
    )


# ---------------------------------------------------------------------------
# Ratings
# ---------------------------------------------------------------------------

@router.get("/recipes/{recipe_id}/ratings", response_model=RatingSummary)
async def get_rating_summary(
    recipe_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    recipe = await _get_recipe_or_404(db, recipe_id)

    user_rating_result = await db.execute(
        select(Rating.score).where(
            Rating.recipe_id == recipe_id,
            Rating.user_id == current_user.id,
        )
    )
    user_score = user_rating_result.scalar_one_or_none()

    return RatingSummary(
        avg_rating=float(recipe.avg_rating) if recipe.avg_rating else None,
        rating_count=recipe.rating_count,
        user_score=user_score,
    )


@router.put("/recipes/{recipe_id}/ratings", response_model=RatingOut)
async def upsert_rating(
    recipe_id: UUID,
    body: RatingCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create or update the current user's rating for a recipe."""
    await _get_recipe_or_404(db, recipe_id)

    result = await db.execute(
        select(Rating).where(
            Rating.recipe_id == recipe_id,
            Rating.user_id == current_user.id,
        )
    )
    rating = result.scalar_one_or_none()

    if rating:
        rating.score = body.score
    else:
        rating = Rating(
            recipe_id=recipe_id,
            user_id=current_user.id,
            score=body.score,
        )
        db.add(rating)

    await db.flush()
    await db.refresh(rating)
    return rating


@router.delete("/recipes/{recipe_id}/ratings", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rating(
    recipe_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Rating).where(
            Rating.recipe_id == recipe_id,
            Rating.user_id == current_user.id,
        )
    )
    rating = result.scalar_one_or_none()
    if not rating:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rating not found")
    await db.delete(rating)


# ---------------------------------------------------------------------------
# Critiques (threaded comments)
# ---------------------------------------------------------------------------

@router.get("/recipes/{recipe_id}/critiques", response_model=list[CritiqueOut])
async def list_critiques(
    recipe_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns top-level critiques only. Fetch replies via /critiques/{id}/replies."""
    await _get_recipe_or_404(db, recipe_id)
    offset = (page - 1) * page_size

    result = await db.execute(
        select(Critique)
        .where(Critique.recipe_id == recipe_id, Critique.parent_id == None)
        .options(selectinload(Critique.user))
        .order_by(Critique.upvotes.desc(), Critique.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    critiques = result.scalars().all()
    return [await _build_critique_out(db, c, current_user) for c in critiques]


@router.post("/recipes/{recipe_id}/critiques", response_model=CritiqueOut, status_code=status.HTTP_201_CREATED)
async def create_critique(
    recipe_id: UUID,
    body: CritiqueCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_recipe_or_404(db, recipe_id)

    # Validate parent exists and belongs to same recipe
    if body.parent_id:
        parent_result = await db.execute(
            select(Critique).where(
                Critique.id == body.parent_id,
                Critique.recipe_id == recipe_id,
            )
        )
        if not parent_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent critique not found on this recipe",
            )

    critique = Critique(
        recipe_id=recipe_id,
        user_id=current_user.id,
        parent_id=body.parent_id,
        body=body.body,
    )
    db.add(critique)
    await db.flush()

    result = await db.execute(
        select(Critique)
        .where(Critique.id == critique.id)
        .options(selectinload(Critique.user))
    )
    critique = result.scalar_one()
    return await _build_critique_out(db, critique, current_user)


@router.get("/critiques/{critique_id}", response_model=CritiqueOut)
async def get_critique(
    critique_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    critique = await _get_critique_or_404(db, critique_id)
    return await _build_critique_out(db, critique, current_user)


@router.get("/critiques/{critique_id}/replies", response_model=list[CritiqueOut])
async def list_replies(
    critique_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_critique_or_404(db, critique_id)
    offset = (page - 1) * page_size

    result = await db.execute(
        select(Critique)
        .where(Critique.parent_id == critique_id)
        .options(selectinload(Critique.user))
        .order_by(Critique.created_at.asc())
        .offset(offset)
        .limit(page_size)
    )
    return [await _build_critique_out(db, c, current_user) for c in result.scalars().all()]


@router.patch("/critiques/{critique_id}", response_model=CritiqueOut)
async def update_critique(
    critique_id: UUID,
    body: CritiqueUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    critique = await _get_critique_or_404(db, critique_id)
    if critique.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your critique")
    critique.body = body.body
    await db.flush()
    return await _build_critique_out(db, critique, current_user)


@router.delete("/critiques/{critique_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_critique(
    critique_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    critique = await _get_critique_or_404(db, critique_id)
    if critique.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your critique")
    await db.delete(critique)


# ---------------------------------------------------------------------------
# Upvotes
# ---------------------------------------------------------------------------

@router.post("/critiques/{critique_id}/upvote", status_code=status.HTTP_204_NO_CONTENT)
async def upvote_critique(
    critique_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    critique = await _get_critique_or_404(db, critique_id)

    if critique.user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot upvote your own critique",
        )
    if await _has_upvoted(db, critique_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Already upvoted",
        )

    db.add(CritiqueUpvote(critique_id=critique_id, user_id=current_user.id))
    critique.upvotes += 1
    await db.flush()


@router.delete("/critiques/{critique_id}/upvote", status_code=status.HTTP_204_NO_CONTENT)
async def remove_upvote(
    critique_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    critique = await _get_critique_or_404(db, critique_id)

    result = await db.execute(
        select(CritiqueUpvote).where(
            CritiqueUpvote.critique_id == critique_id,
            CritiqueUpvote.user_id == current_user.id,
        )
    )
    upvote = result.scalar_one_or_none()
    if not upvote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upvote not found")

    await db.delete(upvote)
    critique.upvotes = max(0, critique.upvotes - 1)
    await db.flush()
