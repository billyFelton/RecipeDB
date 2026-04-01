from __future__ import annotations
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from pydantic import BaseModel, Field
from app.models import RecipeVisibility

class IngredientIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    quantity: Decimal | None = None
    unit: str | None = None
    notes: str | None = None
    sort_order: int = 0

class IngredientOut(IngredientIn):
    id: UUID
    model_config = {"from_attributes": True}

class StepIn(BaseModel):
    step_number: int = Field(ge=1)
    instruction: str = Field(min_length=1)
    media_url: str | None = None

class StepOut(StepIn):
    id: UUID
    model_config = {"from_attributes": True}

class MediaOut(BaseModel):
    id: UUID
    url: str
    media_type: str
    is_cover: bool
    sort_order: int
    model_config = {"from_attributes": True}

class RecipeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None
    visibility: RecipeVisibility = RecipeVisibility.group
    group_id: UUID | None = None
    prep_time_mins: int | None = Field(default=None, ge=0)
    cook_time_mins: int | None = Field(default=None, ge=0)
    servings: int | None = Field(default=None, ge=1)
    cuisine_type: str | None = None
    tags: list[str] = []
    ingredients: list[IngredientIn] = []
    steps: list[StepIn] = []

class RecipeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    visibility: RecipeVisibility | None = None
    prep_time_mins: int | None = None
    cook_time_mins: int | None = None
    servings: int | None = None
    cuisine_type: str | None = None
    tags: list[str] | None = None
    ingredients: list[IngredientIn] | None = None
    steps: list[StepIn] | None = None

class RecipeSummary(BaseModel):
    id: UUID
    title: str
    description: str | None
    visibility: RecipeVisibility
    cuisine_type: str | None
    prep_time_mins: int | None
    cook_time_mins: int | None
    servings: int | None
    avg_rating: Decimal | None
    rating_count: int
    created_at: datetime
    updated_at: datetime
    tags: list[str] = []
    cover_image_url: str | None = None
    model_config = {"from_attributes": True}

class RecipeDetail(RecipeSummary):
    author_id: UUID
    group_id: UUID | None
    ingredients: list[IngredientOut] = []
    steps: list[StepOut] = []
    media: list[MediaOut] = []

class RecipeSearchParams(BaseModel):
    q: str | None = None
    cuisine_type: str | None = None
    tags: list[str] = []
    max_cook_time: int | None = None
    min_rating: float | None = None
    visibility: RecipeVisibility | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)
