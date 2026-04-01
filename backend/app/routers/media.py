from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Recipe, RecipeMedia, User
from app.schemas.media import MediaUploadOut, MediaReorderItem, PresignedUploadOut, SetCoverRequest
from app.services.storage import (
    ALLOWED_TYPES, MAX_IMAGE_BYTES, MAX_VIDEO_BYTES,
    delete_file, presigned_upload_url, upload_file,
    ALLOWED_IMAGE_TYPES,
)

router = APIRouter(tags=["media"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_recipe_or_404(db: AsyncSession, recipe_id: UUID) -> Recipe:
    result = await db.execute(select(Recipe).where(Recipe.id == recipe_id))
    recipe = result.scalar_one_or_none()
    if not recipe:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recipe not found")
    return recipe


async def _assert_author(recipe: Recipe, user: User):
    if recipe.author_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not the recipe author")


def _validate_content_type(content_type: str):
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported media type. Allowed: {', '.join(sorted(ALLOWED_TYPES))}",
        )


def _validate_size(data: bytes, content_type: str):
    limit = MAX_VIDEO_BYTES if content_type.startswith("video/") else MAX_IMAGE_BYTES
    if len(data) > limit:
        mb = limit // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size: {mb} MB",
        )


# ---------------------------------------------------------------------------
# Direct upload (small files — image goes through the API)
# ---------------------------------------------------------------------------

@router.post(
    "/recipes/{recipe_id}/media",
    response_model=MediaUploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_recipe_media(
    recipe_id: UUID,
    file: UploadFile = File(...),
    is_cover: bool = Form(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    recipe = await _get_recipe_or_404(db, recipe_id)
    await _assert_author(recipe, current_user)

    content_type = file.content_type or ""
    _validate_content_type(content_type)

    data = await file.read()
    _validate_size(data, content_type)

    url = upload_file(data, content_type, folder=f"recipes/{recipe_id}")
    media_type = "image" if content_type in ALLOWED_IMAGE_TYPES else "video"

    # Count existing media for sort_order
    count_result = await db.execute(
        select(RecipeMedia).where(RecipeMedia.recipe_id == recipe_id)
    )
    sort_order = len(count_result.scalars().all())

    # If setting as cover, unset any existing cover
    if is_cover:
        existing_result = await db.execute(
            select(RecipeMedia).where(
                RecipeMedia.recipe_id == recipe_id,
                RecipeMedia.is_cover == True,
            )
        )
        for existing in existing_result.scalars().all():
            existing.is_cover = False

    media = RecipeMedia(
        recipe_id=recipe_id,
        url=url,
        media_type=media_type,
        is_cover=is_cover,
        sort_order=sort_order,
    )
    db.add(media)
    await db.flush()
    await db.refresh(media)
    return media


# ---------------------------------------------------------------------------
# Presigned URL (large files — client uploads directly to MinIO/S3)
# ---------------------------------------------------------------------------

@router.post("/recipes/{recipe_id}/media/presigned", response_model=PresignedUploadOut)
async def get_presigned_upload_url(
    recipe_id: UUID,
    content_type: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a presigned PUT URL. The client uploads directly to object storage,
    then calls POST /recipes/{id}/media/confirm to register the media record.
    """
    recipe = await _get_recipe_or_404(db, recipe_id)
    await _assert_author(recipe, current_user)
    _validate_content_type(content_type)

    presigned, final_url = presigned_upload_url(content_type, folder=f"recipes/{recipe_id}")
    return PresignedUploadOut(presigned_url=presigned, final_url=final_url)


@router.post(
    "/recipes/{recipe_id}/media/confirm",
    response_model=MediaUploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_presigned_upload(
    recipe_id: UUID,
    url: str = Form(...),
    content_type: str = Form(...),
    is_cover: bool = Form(default=False),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    After a successful presigned upload, call this to create the DB record.
    """
    recipe = await _get_recipe_or_404(db, recipe_id)
    await _assert_author(recipe, current_user)
    _validate_content_type(content_type)

    media_type = "image" if content_type in ALLOWED_IMAGE_TYPES else "video"

    count_result = await db.execute(
        select(RecipeMedia).where(RecipeMedia.recipe_id == recipe_id)
    )
    sort_order = len(count_result.scalars().all())

    if is_cover:
        existing_result = await db.execute(
            select(RecipeMedia).where(
                RecipeMedia.recipe_id == recipe_id,
                RecipeMedia.is_cover == True,
            )
        )
        for existing in existing_result.scalars().all():
            existing.is_cover = False

    media = RecipeMedia(
        recipe_id=recipe_id,
        url=url,
        media_type=media_type,
        is_cover=is_cover,
        sort_order=sort_order,
    )
    db.add(media)
    await db.flush()
    await db.refresh(media)
    return media


# ---------------------------------------------------------------------------
# List, reorder, set cover, delete
# ---------------------------------------------------------------------------

@router.get("/recipes/{recipe_id}/media", response_model=list[MediaUploadOut])
async def list_recipe_media(
    recipe_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_recipe_or_404(db, recipe_id)
    result = await db.execute(
        select(RecipeMedia)
        .where(RecipeMedia.recipe_id == recipe_id)
        .order_by(RecipeMedia.sort_order)
    )
    return result.scalars().all()


@router.post("/recipes/{recipe_id}/media/reorder", response_model=list[MediaUploadOut])
async def reorder_media(
    recipe_id: UUID,
    items: list[MediaReorderItem],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    recipe = await _get_recipe_or_404(db, recipe_id)
    await _assert_author(recipe, current_user)

    for item in items:
        result = await db.execute(
            select(RecipeMedia).where(
                RecipeMedia.id == item.media_id,
                RecipeMedia.recipe_id == recipe_id,
            )
        )
        media = result.scalar_one_or_none()
        if media:
            media.sort_order = item.sort_order

    await db.flush()
    result = await db.execute(
        select(RecipeMedia)
        .where(RecipeMedia.recipe_id == recipe_id)
        .order_by(RecipeMedia.sort_order)
    )
    return result.scalars().all()


@router.post("/recipes/{recipe_id}/media/cover", response_model=MediaUploadOut)
async def set_cover(
    recipe_id: UUID,
    body: SetCoverRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    recipe = await _get_recipe_or_404(db, recipe_id)
    await _assert_author(recipe, current_user)

    # Unset all covers
    existing_result = await db.execute(
        select(RecipeMedia).where(RecipeMedia.recipe_id == recipe_id)
    )
    for m in existing_result.scalars().all():
        m.is_cover = m.id == body.media_id

    await db.flush()

    result = await db.execute(
        select(RecipeMedia).where(RecipeMedia.id == body.media_id)
    )
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")
    return media


@router.delete("/recipes/{recipe_id}/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    recipe_id: UUID,
    media_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    recipe = await _get_recipe_or_404(db, recipe_id)
    await _assert_author(recipe, current_user)

    result = await db.execute(
        select(RecipeMedia).where(
            RecipeMedia.id == media_id,
            RecipeMedia.recipe_id == recipe_id,
        )
    )
    media = result.scalar_one_or_none()
    if not media:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found")

    delete_file(media.url)
    await db.delete(media)
