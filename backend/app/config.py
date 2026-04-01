from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # App
    app_name: str = "RecipeDB API"
    environment: str = "development"
    debug: bool = False

    # Database
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_host: str = "db"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Redis
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str

    @property
    def redis_url(self) -> str:
        return f"redis://:{self.redis_password}@{self.redis_host}:{self.redis_port}/0"

    # JWT
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 30

    # Object storage (MinIO / S3)
    s3_endpoint_url: str = "http://minio:9000"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket_name: str = "recipedb-media"
    s3_region: str = "us-east-1"

    # APNs (push notifications)
    apns_key_id: str = ""
    apns_team_id: str = ""
    apns_bundle_id: str = ""
    apns_key_path: str = "/app/apns.p8"
    apns_production: bool = False

    # CORS
    allowed_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
