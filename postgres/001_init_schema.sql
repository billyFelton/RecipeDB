-- =============================================================================
-- Recipe Platform — Initial Schema Migration
-- 001_initial_schema.sql
-- PostgreSQL 15+
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "pg_trgm";       -- trigram indexes for search
CREATE EXTENSION IF NOT EXISTS "unaccent";      -- accent-insensitive search

-- ---------------------------------------------------------------------------
-- Utility: updated_at trigger function
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- DOMAIN 1: IDENTITY & AUTH
-- =============================================================================

CREATE TABLE users (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  username        TEXT        NOT NULL UNIQUE,
  email           TEXT        NOT NULL UNIQUE,
  password_hash   TEXT        NOT NULL,
  display_name    TEXT,
  avatar_url      TEXT,
  bio             TEXT,
  is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Refresh tokens for JWT rotation
CREATE TABLE refresh_tokens (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash      TEXT        NOT NULL UNIQUE,
  expires_at      TIMESTAMPTZ NOT NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);

-- =============================================================================
-- DOMAIN 2: GROUPS & MEMBERSHIP
-- =============================================================================

CREATE TABLE groups (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  name            TEXT        NOT NULL,
  description     TEXT,
  owner_id        UUID        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  invite_code     TEXT        UNIQUE DEFAULT encode(gen_random_bytes(6), 'hex'),
  is_public       BOOLEAN     NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_groups_updated_at
  BEFORE UPDATE ON groups
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_groups_owner_id ON groups(owner_id);

CREATE TYPE group_role AS ENUM ('owner', 'admin', 'member');

CREATE TABLE group_members (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id        UUID        NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id         UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role            group_role  NOT NULL DEFAULT 'member',
  joined_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (group_id, user_id)
);

CREATE INDEX idx_group_members_group_id ON group_members(group_id);
CREATE INDEX idx_group_members_user_id  ON group_members(user_id);

-- =============================================================================
-- DOMAIN 3: RECIPES
-- =============================================================================

CREATE TYPE recipe_visibility AS ENUM ('private', 'group', 'shared', 'public');

CREATE TABLE recipes (
  id              UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
  author_id       UUID              NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  group_id        UUID              REFERENCES groups(id) ON DELETE SET NULL,
  title           TEXT              NOT NULL,
  description     TEXT,
  visibility      recipe_visibility NOT NULL DEFAULT 'group',
  prep_time_mins  INT,
  cook_time_mins  INT,
  servings        INT,
  cuisine_type    TEXT,
  avg_rating      NUMERIC(3,2)      DEFAULT 0,
  rating_count    INT               NOT NULL DEFAULT 0,
  -- Full-text search vector (auto-maintained via trigger)
  search_vector   TSVECTOR,
  created_at      TIMESTAMPTZ       NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_recipes_updated_at
  BEFORE UPDATE ON recipes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Full-text search trigger
CREATE OR REPLACE FUNCTION recipes_search_vector_update()
RETURNS TRIGGER AS $$
BEGIN
  NEW.search_vector :=
    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(NEW.cuisine_type, '')), 'C');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_recipes_search_vector
  BEFORE INSERT OR UPDATE ON recipes
  FOR EACH ROW EXECUTE FUNCTION recipes_search_vector_update();

CREATE INDEX idx_recipes_author_id     ON recipes(author_id);
CREATE INDEX idx_recipes_group_id      ON recipes(group_id);
CREATE INDEX idx_recipes_visibility    ON recipes(visibility);
CREATE INDEX idx_recipes_search_vector ON recipes USING GIN(search_vector);
CREATE INDEX idx_recipes_created_at    ON recipes(created_at DESC);

-- Ingredients
CREATE TABLE recipe_ingredients (
  id          UUID    PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id   UUID    NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  name        TEXT    NOT NULL,
  quantity    NUMERIC,
  unit        TEXT,
  notes       TEXT,
  sort_order  INT     NOT NULL DEFAULT 0
);

CREATE INDEX idx_recipe_ingredients_recipe_id ON recipe_ingredients(recipe_id);

-- Steps
CREATE TABLE recipe_steps (
  id           UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id    UUID  NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  step_number  INT   NOT NULL,
  instruction  TEXT  NOT NULL,
  media_url    TEXT,
  UNIQUE (recipe_id, step_number)
);

CREATE INDEX idx_recipe_steps_recipe_id ON recipe_steps(recipe_id);

-- Media (photos/videos attached to a recipe)
CREATE TABLE recipe_media (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id   UUID        NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  url         TEXT        NOT NULL,
  media_type  TEXT        NOT NULL DEFAULT 'image',   -- 'image' | 'video'
  is_cover    BOOLEAN     NOT NULL DEFAULT FALSE,
  sort_order  INT         NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_recipe_media_recipe_id ON recipe_media(recipe_id);

-- Tags (denormalized for simplicity; use a tag table + join if you want autocomplete)
CREATE TABLE recipe_tags (
  id          UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id   UUID  NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  tag         TEXT  NOT NULL,
  UNIQUE (recipe_id, tag)
);

CREATE INDEX idx_recipe_tags_recipe_id ON recipe_tags(recipe_id);
CREATE INDEX idx_recipe_tags_tag       ON recipe_tags(tag);

-- Shares (explicit cross-group or cross-user sharing)
CREATE TABLE recipe_shares (
  id               UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id        UUID        NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  shared_by        UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_user_id   UUID        REFERENCES users(id)  ON DELETE CASCADE,
  target_group_id  UUID        REFERENCES groups(id) ON DELETE CASCADE,
  shared_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  -- Must share to exactly one target
  CONSTRAINT chk_share_target CHECK (
    (target_user_id IS NOT NULL AND target_group_id IS NULL) OR
    (target_user_id IS NULL     AND target_group_id IS NOT NULL)
  )
);

CREATE INDEX idx_recipe_shares_recipe_id       ON recipe_shares(recipe_id);
CREATE INDEX idx_recipe_shares_target_user_id  ON recipe_shares(target_user_id);
CREATE INDEX idx_recipe_shares_target_group_id ON recipe_shares(target_group_id);

-- =============================================================================
-- DOMAIN 4: SOCIAL GRAPH
-- =============================================================================

-- Followers/following
CREATE TABLE follows (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  follower_id  UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  following_id UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (follower_id, following_id),
  CONSTRAINT chk_no_self_follow CHECK (follower_id <> following_id)
);

CREATE INDEX idx_follows_follower_id  ON follows(follower_id);
CREATE INDEX idx_follows_following_id ON follows(following_id);

-- Ratings (1–5 stars)
CREATE TABLE ratings (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id   UUID        NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  user_id     UUID        NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  score       SMALLINT    NOT NULL CHECK (score BETWEEN 1 AND 5),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (recipe_id, user_id)
);

CREATE TRIGGER trg_ratings_updated_at
  BEFORE UPDATE ON ratings
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_ratings_recipe_id ON ratings(recipe_id);
CREATE INDEX idx_ratings_user_id   ON ratings(user_id);

-- Maintain avg_rating + rating_count on recipes automatically
CREATE OR REPLACE FUNCTION update_recipe_rating()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE recipes
  SET
    avg_rating   = (SELECT AVG(score)   FROM ratings WHERE recipe_id = COALESCE(NEW.recipe_id, OLD.recipe_id)),
    rating_count = (SELECT COUNT(*)     FROM ratings WHERE recipe_id = COALESCE(NEW.recipe_id, OLD.recipe_id))
  WHERE id = COALESCE(NEW.recipe_id, OLD.recipe_id);
  RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ratings_sync
  AFTER INSERT OR UPDATE OR DELETE ON ratings
  FOR EACH ROW EXECUTE FUNCTION update_recipe_rating();

-- Critiques (threaded comments for community review)
CREATE TABLE critiques (
  id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  recipe_id   UUID        NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
  user_id     UUID        NOT NULL REFERENCES users(id)   ON DELETE CASCADE,
  parent_id   UUID        REFERENCES critiques(id)        ON DELETE CASCADE,
  body        TEXT        NOT NULL,
  upvotes     INT         NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER trg_critiques_updated_at
  BEFORE UPDATE ON critiques
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX idx_critiques_recipe_id ON critiques(recipe_id);
CREATE INDEX idx_critiques_parent_id ON critiques(parent_id);
CREATE INDEX idx_critiques_user_id   ON critiques(user_id);

-- Upvote tracking (one upvote per user per critique)
CREATE TABLE critique_upvotes (
  critique_id  UUID NOT NULL REFERENCES critiques(id) ON DELETE CASCADE,
  user_id      UUID NOT NULL REFERENCES users(id)     ON DELETE CASCADE,
  PRIMARY KEY (critique_id, user_id)
);

-- =============================================================================
-- DOMAIN 5: CHAT
-- =============================================================================

CREATE TYPE chat_room_type AS ENUM ('group_general', 'recipe_discussion', 'direct');

CREATE TABLE chat_rooms (
  id          UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id    UUID              REFERENCES groups(id) ON DELETE CASCADE,
  name        TEXT,
  room_type   chat_room_type    NOT NULL DEFAULT 'group_general',
  created_at  TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_chat_rooms_group_id ON chat_rooms(group_id);

-- Direct message rooms: exactly two participants
CREATE TABLE chat_room_members (
  room_id     UUID NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES users(id)      ON DELETE CASCADE,
  PRIMARY KEY (room_id, user_id)
);

CREATE TABLE chat_messages (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  room_id      UUID        NOT NULL REFERENCES chat_rooms(id)  ON DELETE CASCADE,
  sender_id    UUID        NOT NULL REFERENCES users(id)        ON DELETE RESTRICT,
  -- Optional: attach a recipe card inline in chat
  recipe_id    UUID        REFERENCES recipes(id)               ON DELETE SET NULL,
  body         TEXT        NOT NULL,
  sent_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  edited_at    TIMESTAMPTZ
);

CREATE INDEX idx_chat_messages_room_id   ON chat_messages(room_id, sent_at DESC);
CREATE INDEX idx_chat_messages_sender_id ON chat_messages(sender_id);

-- =============================================================================
-- DOMAIN 6: NOTIFICATIONS
-- =============================================================================

CREATE TYPE notification_type AS ENUM (
  'new_follower',
  'recipe_shared',
  'new_critique',
  'critique_reply',
  'critique_upvote',
  'new_rating',
  'group_invite',
  'chat_mention'
);

CREATE TABLE notifications (
  id          UUID              PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID              NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  type        notification_type NOT NULL,
  -- Flexible JSON payload: actor_id, recipe_id, group_id, etc.
  payload     JSONB             NOT NULL DEFAULT '{}',
  read        BOOLEAN           NOT NULL DEFAULT FALSE,
  created_at  TIMESTAMPTZ       NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_user_id    ON notifications(user_id, created_at DESC);
CREATE INDEX idx_notifications_unread     ON notifications(user_id) WHERE read = FALSE;

-- =============================================================================
-- SEED: default admin user (change password before deploying)
-- =============================================================================
INSERT INTO users (username, email, password_hash, display_name)
VALUES (
  'admin',
  'admin@example.com',
  -- bcrypt hash of 'changeme' — replace before going live
  '$2b$12$placeholderHashReplaceBeforeDeployxxxxxxxxxxxxxxxxxxxxxx',
  'Admin'
);
