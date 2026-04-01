from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, or_, and_, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    GroupMember, Recipe, RecipeIngredient,
    RecipeMedia, RecipeShare, RecipeStep, RecipeTag, RecipeVisibility, User,
)
from app.schemas.recipes import RecipeCreate, RecipeDetail, RecipeSummary, RecipeUpdate

router = APIRouter(prefix="/recipes", tags=["recipes"])


# ---------------------------------------------------------------------------
# Visibility helper
# ---------------------------------------------------------------------------

def _visibility_filter(current_user: User):
    """Build a WHERE clause that respects recipe visibility rules."""
    user_group_ids = select(GroupMember.group_id).where(GroupMember.user_id == current_user.id)
    shared_recipe_ids = select(RecipeShare.recipe_id).where(RecipeShare.target_user_id == current_user.id)

    return or_(
        Recipe.author_id == current_user.id,
        Recipe.visibility == RecipeVisibility.public,
        and_(
            Recipe.visibility == RecipeVisibility.group,
            Recipe.group_id.in_(user_group_ids),
        ),
        and_(
            Recipe.visibility == RecipeVisibility.shared,
            Recipe.id.in_(shared_recipe_ids),
        ),
    )


def _full_load():
    return [
        selectinload(Recipe.ingredients),
        selectinload(Recipe.steps),
        selectinload(Recipe.media),
        selectinload(Recipe.tags),
    ]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[RecipeSummary])
async def list_recipes(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Recipe)
        .where(_visibility_filter(current_user))
        .order_by(Recipe.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .options(selectinload(Recipe.tags), selectinload(Recipe.media))
    )
    return result.scalars().all()


@router.get("/search", response_model=list[RecipeSummary])
async def search_recipes(
    q: str | None = Query(default=None),
    cuisine_type: str | None = Query(default=None),
    max_cook_time: int | None = Query(default=None),
    min_rating: float | None = Query(default=None),
    tags: list[str] = Query(default=[]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = [_visibility_filter(current_user)]

    if q:
        filters.append(Recipe.search_vector.match(q, postgresql_regconfig="english"))
    if cuisine_type:
        filters.append(func.lower(Recipe.cuisine_type) == cuisine_type.lower())
    if max_cook_time is not None:
        filters.append(Recipe.cook_time_mins <= max_cook_time)
    if min_rating is not None:
        filters.append(Recipe.avg_rating >= min_rating)
    if tags:
        for tag in tags:
            filters.append(
                Recipe.id.in_(select(RecipeTag.recipe_id).where(RecipeTag.tag == tag))
            )

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Recipe)
        .where(and_(*filters))
        .order_by(Recipe.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .options(selectinload(Recipe.tags), selectinload(Recipe.media))
    )
    return result.scalars().all()


@router.post("", response_model=RecipeDetail, status_code=status.HTTP_201_CREATED)
async def create_recipe(
    body: RecipeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    recipe = Recipe(
        author_id=current_user.id,
        group_id=body.group_id,
        title=body.title,
        description=body.description,
        visibility=body.visibility,
        prep_time_mins=body.prep_time_mins,
        cook_time_mins=body.cook_time_mins,
        servings=body.servings,
        cuisine_type=body.cuisine_type,
    )
    db.add(recipe)
    await db.flush()

    for ing in body.ingredients:
        db.add(RecipeIngredient(recipe_id=recipe.id, **ing.model_dump()))
    for step in body.steps:
        db.add(RecipeStep(recipe_id=recipe.id, **step.model_dump()))
    for tag in body.tags:
        db.add(RecipeTag(recipe_id=recipe.id, tag=tag.lower().strip()))

    await db.flush()
    await db.refresh(recipe, ["ingredients", "steps", "media", "tags"])
    return recipe


@router.get("/{recipe_id}", response_model=RecipeDetail)
async def get_recipe(
    recipe_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Recipe)
        .where(Recipe.id == recipe_id, _visibility_filter(current_user))
        .options(*_full_load())
    )
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return recipe


@router.patch("/{recipe_id}", response_model=RecipeDetail)
async def update_recipe(
    recipe_id: UUID,
    body: RecipeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Recipe)
        .where(Recipe.id == recipe_id)
        .options(*_full_load())
    )
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    if recipe.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the recipe author")

    update_data = body.model_dump(exclude_unset=True)

    # Handle nested replacements
    if "ingredients" in update_data:
        for ing in recipe.ingredients:
            await db.delete(ing)
        for ing in body.ingredients:
            db.add(RecipeIngredient(recipe_id=recipe.id, **ing.model_dump()))
        update_data.pop("ingredients")

    if "steps" in update_data:
        for step in recipe.steps:
            await db.delete(step)
        for step in body.steps:
            db.add(RecipeStep(recipe_id=recipe.id, **step.model_dump()))
        update_data.pop("steps")

    if "tags" in update_data:
        for tag in recipe.tags:
            await db.delete(tag)
        for tag in body.tags:
            db.add(RecipeTag(recipe_id=recipe.id, tag=tag.lower().strip()))
        update_data.pop("tags")

    for field, value in update_data.items():
        setattr(recipe, field, value)

    await db.flush()
    await db.refresh(recipe, ["ingredients", "steps", "media", "tags"])
    return recipe


@router.delete("/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipe(
    recipe_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    if recipe.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the recipe author")
    await db.delete(recipe)
