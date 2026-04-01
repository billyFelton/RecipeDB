import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean, Column, DateTime, Enum, ForeignKey,
    Integer, Numeric, SmallInteger, String, Text,
    UniqueConstraint, CheckConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, TSVECTOR
from sqlalchemy.orm import relationship
from app.database import Base
import enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class GroupRole(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class RecipeVisibility(str, enum.Enum):
    private = "private"
    group = "group"
    shared = "shared"
    public = "public"


class ChatRoomType(str, enum.Enum):
    group_general = "group_general"
    recipe_discussion = "recipe_discussion"
    direct = "direct"


class NotificationType(str, enum.Enum):
    new_follower = "new_follower"
    recipe_shared = "recipe_shared"
    new_critique = "new_critique"
    critique_reply = "critique_reply"
    critique_upvote = "critique_upvote"
    new_rating = "new_rating"
    group_invite = "group_invite"
    chat_mention = "chat_mention"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username      = Column(String, nullable=False, unique=True)
    email         = Column(String, nullable=False, unique=True)
    password_hash = Column(String, nullable=False)
    display_name  = Column(String)
    avatar_url    = Column(String)
    bio           = Column(Text)
    is_active     = Column(Boolean, nullable=False, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    recipes         = relationship("Recipe", back_populates="author", foreign_keys="Recipe.author_id")
    owned_groups    = relationship("Group", back_populates="owner")
    group_memberships = relationship("GroupMember", back_populates="user")
    refresh_tokens  = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")
    notifications   = relationship("Notification", back_populates="user", cascade="all, delete-orphan")


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String, nullable=False, unique=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="refresh_tokens")


class Group(Base):
    __tablename__ = "groups"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name        = Column(String, nullable=False)
    description = Column(Text)
    owner_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    invite_code = Column(String, unique=True)
    is_public   = Column(Boolean, nullable=False, default=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at  = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    owner   = relationship("User", back_populates="owned_groups")
    members = relationship("GroupMember", back_populates="group", cascade="all, delete-orphan")
    recipes = relationship("Recipe", back_populates="group")
    chat_rooms = relationship("ChatRoom", back_populates="group", cascade="all, delete-orphan")


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (UniqueConstraint("group_id", "user_id"),)

    id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id  = Column(UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    user_id   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role      = Column(Enum(GroupRole), nullable=False, default=GroupRole.member)
    joined_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    group = relationship("Group", back_populates="members")
    user  = relationship("User", back_populates="group_memberships")


class Recipe(Base):
    __tablename__ = "recipes"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    author_id      = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    group_id       = Column(UUID(as_uuid=True), ForeignKey("groups.id", ondelete="SET NULL"))
    title          = Column(String, nullable=False)
    description    = Column(Text)
    visibility     = Column(Enum(RecipeVisibility), nullable=False, default=RecipeVisibility.group)
    prep_time_mins = Column(Integer)
    cook_time_mins = Column(Integer)
    servings       = Column(Integer)
    cuisine_type   = Column(String)
    avg_rating     = Column(Numeric(3, 2), default=0)
    rating_count   = Column(Integer, nullable=False, default=0)
    search_vector  = Column(TSVECTOR)
    created_at     = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at     = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    author      = relationship("User", back_populates="recipes", foreign_keys=[author_id])
    group       = relationship("Group", back_populates="recipes")
    ingredients = relationship("RecipeIngredient", back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeIngredient.sort_order")
    steps       = relationship("RecipeStep", back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeStep.step_number")
    media       = relationship("RecipeMedia", back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeMedia.sort_order")
    tags        = relationship("RecipeTag", back_populates="recipe", cascade="all, delete-orphan")
    ratings     = relationship("Rating", back_populates="recipe", cascade="all, delete-orphan")
    critiques   = relationship("Critique", back_populates="recipe", cascade="all, delete-orphan")
    shares      = relationship("RecipeShare", back_populates="recipe", cascade="all, delete-orphan")


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id  = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    name       = Column(String, nullable=False)
    quantity   = Column(Numeric)
    unit       = Column(String)
    notes      = Column(String)
    sort_order = Column(Integer, nullable=False, default=0)

    recipe = relationship("Recipe", back_populates="ingredients")


class RecipeStep(Base):
    __tablename__ = "recipe_steps"
    __table_args__ = (UniqueConstraint("recipe_id", "step_number"),)

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id   = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    step_number = Column(Integer, nullable=False)
    instruction = Column(Text, nullable=False)
    media_url   = Column(String)

    recipe = relationship("Recipe", back_populates="steps")


class RecipeMedia(Base):
    __tablename__ = "recipe_media"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id  = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    url        = Column(String, nullable=False)
    media_type = Column(String, nullable=False, default="image")
    is_cover   = Column(Boolean, nullable=False, default=False)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    recipe = relationship("Recipe", back_populates="media")


class RecipeTag(Base):
    __tablename__ = "recipe_tags"
    __table_args__ = (UniqueConstraint("recipe_id", "tag"),)

    id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    tag       = Column(String, nullable=False)

    recipe = relationship("Recipe", back_populates="tags")


class RecipeShare(Base):
    __tablename__ = "recipe_shares"

    id               = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id        = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    shared_by        = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    target_user_id   = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"))
    target_group_id  = Column(UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"))
    shared_at        = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    recipe = relationship("Recipe", back_populates="shares")


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (
        UniqueConstraint("follower_id", "following_id"),
        CheckConstraint("follower_id <> following_id", name="chk_no_self_follow"),
    )

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    follower_id  = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    following_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (UniqueConstraint("recipe_id", "user_id"),)

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id  = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    score      = Column(SmallInteger, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    recipe = relationship("Recipe", back_populates="ratings")


class Critique(Base):
    __tablename__ = "critiques"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recipe_id  = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="CASCADE"), nullable=False)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id  = Column(UUID(as_uuid=True), ForeignKey("critiques.id", ondelete="CASCADE"))
    body       = Column(Text, nullable=False)
    upvotes    = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    recipe  = relationship("Recipe", back_populates="critiques")
    replies = relationship("Critique", back_populates="parent")
    parent  = relationship("Critique", back_populates="replies", remote_side="Critique.id")


class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id   = Column(UUID(as_uuid=True), ForeignKey("groups.id", ondelete="CASCADE"))
    name       = Column(String)
    room_type  = Column(Enum(ChatRoomType), nullable=False, default=ChatRoomType.group_general)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    group    = relationship("Group", back_populates="chat_rooms")
    messages = relationship("ChatMessage", back_populates="room", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    room_id   = Column(UUID(as_uuid=True), ForeignKey("chat_rooms.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    recipe_id = Column(UUID(as_uuid=True), ForeignKey("recipes.id", ondelete="SET NULL"))
    body      = Column(Text, nullable=False)
    sent_at   = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    edited_at = Column(DateTime(timezone=True))

    room = relationship("ChatRoom", back_populates="messages")


class Notification(Base):
    __tablename__ = "notifications"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id    = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type       = Column(Enum(NotificationType), nullable=False)
    payload    = Column(JSONB, nullable=False, default=dict)
    read       = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="notifications")
