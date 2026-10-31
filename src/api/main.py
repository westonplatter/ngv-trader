"""FastAPI application for ngtrader."""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.api.routers import (
    accounts,
    activated_products,
    admin,
    events,
    flexquery_tokens,
    futures,
    jobs,
    orders,
    positions,
    reports,
    strategies,
    structures,
    tags,
    tasks,
    trade_groups,
    tradebot,
    trades,
    user_preferences,
    watch_lists,
    workers,
)
from src.db import get_engine
from src.services.errors import ServiceError

logger = logging.getLogger(__name__)

_env_name = os.environ.get("ENV", "dev")
load_dotenv(f".env.{_env_name}")


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
            "Cannot connect to PostgreSQL. Is the database running? Check DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD in your .env file. Error: %s",
            exc,
        )
        raise SystemExit(1) from exc
    yield


app = FastAPI(title="ngtrader", lifespan=lifespan)


@app.exception_handler(ServiceError)
def service_error_handler(_request: Request, exc: ServiceError) -> JSONResponse:
    """Bad input a service rejected: the same ``detail`` shape as ``HTTPException``."""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


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


app.include_router(accounts.router, prefix="/api/v1", tags=["Accounts"])
app.include_router(flexquery_tokens.router, prefix="/api/v1", tags=["FlexQuery Tokens"])
app.include_router(positions.router, prefix="/api/v1", tags=["Positions"])
app.include_router(orders.router, prefix="/api/v1", tags=["Orders"])
app.include_router(trades.router, prefix="/api/v1", tags=["Trades"])
app.include_router(trade_groups.router, prefix="/api/v1", tags=["Trade Groups"])
app.include_router(strategies.router, prefix="/api/v1", tags=["Strategies"])
app.include_router(tags.router, prefix="/api/v1", tags=["Tags"])
app.include_router(tasks.router, prefix="/api/v1", tags=["Tasks"])
app.include_router(reports.router, prefix="/api/v1", tags=["Reports"])
app.include_router(watch_lists.router, prefix="/api/v1", tags=["Watch Lists"])
app.include_router(jobs.router, prefix="/api/v1", tags=["Jobs"])
app.include_router(workers.router, prefix="/api/v1", tags=["Workers"])
app.include_router(tradebot.router, prefix="/api/v1", tags=["Tradebot"])
app.include_router(futures.router, prefix="/api/v1", tags=["Futures"])
app.include_router(activated_products.router, prefix="/api/v1", tags=["Activated Products"])
app.include_router(user_preferences.router, prefix="/api/v1", tags=["User Preferences"])
app.include_router(structures.router, prefix="/api/v1", tags=["Structures"])
app.include_router(events.router, prefix="/api/v1", tags=["Events"])
app.include_router(admin.router, prefix="/api/v1", tags=["Admin"])
