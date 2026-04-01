from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.redis_client import close_redis, get_redis
from app.routers import auth, recipes, groups, social

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await get_redis()
    yield
    # Shutdown
    await close_redis()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(auth.router,    prefix="/api/v1")
app.include_router(recipes.router, prefix="/api/v1")
app.include_router(groups.router,  prefix="/api/v1")
app.include_router(social.router,  prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "environment": settings.environment}
