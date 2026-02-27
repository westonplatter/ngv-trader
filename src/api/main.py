"""FastAPI application for ngtrader."""

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routers import (
    accounts,
    jobs,
    orders,
    positions,
    spreads,
    tradebot,
    watch_lists,
    workers,
)

load_dotenv()

app = FastAPI(title="ngtrader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(accounts.router, prefix="/api/v1", tags=["Accounts"])
app.include_router(positions.router, prefix="/api/v1", tags=["Positions"])
app.include_router(spreads.router, prefix="/api/v1", tags=["Spreads"])
app.include_router(orders.router, prefix="/api/v1", tags=["Orders"])
app.include_router(jobs.router, prefix="/api/v1", tags=["Jobs"])
app.include_router(tradebot.router, prefix="/api/v1", tags=["Tradebot"])
app.include_router(watch_lists.router, prefix="/api/v1", tags=["Watch Lists"])
app.include_router(workers.router, prefix="/api/v1", tags=["Workers"])
