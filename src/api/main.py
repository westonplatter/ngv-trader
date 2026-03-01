"""FastAPI application for ngtrader."""

import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.api.routers import (
    accounts,
    jobs,
    orders,
    positions,
    tradebot,
    trades,
    user_preferences,
    watch_lists,
    workers,
)
from src.db import get_engine

logger = logging.getLogger(__name__)

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate database connectivity on startup
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified.")
    except Exception as exc:
        logger.error(
            "Cannot connect to PostgreSQL. Is the database running? " "Check DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD in your .env file. " "Error: %s",
            exc,
        )
        raise SystemExit(1) from exc
    yield


app = FastAPI(title="ngtrader", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/v1/health")
def health():
    """Check API and database connectivity."""
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception as exc:
        return {"status": "error", "database": str(exc)}


app.include_router(accounts.router, prefix="/api/v1")
app.include_router(positions.router, prefix="/api/v1")
app.include_router(orders.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(tradebot.router, prefix="/api/v1")
app.include_router(trades.router, prefix="/api/v1")
app.include_router(user_preferences.router, prefix="/api/v1")
app.include_router(watch_lists.router, prefix="/api/v1")
app.include_router(workers.router, prefix="/api/v1")
