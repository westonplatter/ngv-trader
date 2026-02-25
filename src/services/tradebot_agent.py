# BOUNDARY: This module must NEVER import ib_async or make direct broker connections.
# All IB interactions happen through worker:jobs. Order execution is disabled.

"""LLM-backed tradebot agent with LangGraph tool workflows."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Sequence, TypedDict
from urllib import error, parse, request

from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.models import (
    Account,
    Job,
    Order,
    OrderEvent,
    Position,
    WatchList,
    WatchListInstrument,
)
from src.services.cl_contracts import (
    DEFAULT_CL_MIN_DAYS_TO_EXPIRY,
    display_contract_month,
    normalize_contract_month_input,
)
from src.services.contract_lookup import find_contracts
from src.services.jobs import (
    JOB_TYPE_CONTRACTS_SYNC,
    JOB_TYPE_POSITIONS_SYNC,
    JOB_TYPE_WATCHLIST_ADD_INSTRUMENT,
    enqueue_job,
)
from src.utils.env_vars import get_int_env, get_str_env
from src.utils.ibkr_account import mask_ibkr_account

_SYSTEM_PROMPT = (
    "You are Tradebot, an operations assistant for a live trading desk. "
    "Use tools for factual data access and side effects. "
    "Never fabricate DB data, job IDs, order IDs, fills, or statuses. "
    "When a user asks for current state, call read tools first. "
    "You can enqueue positions sync jobs and contracts sync jobs. "
    "For informational queries about contracts (front month, available months, contract details), use lookup_contract. "
    "Order execution is disabled in this system. "
    "If asked to place, queue, submit, or cancel an order, explain that execution is disabled "
    "and offer read-only alternatives like listing orders/positions or looking up contracts. "
    "You can also manage watch lists: create watch lists, add instruments to them, list them, and remove instruments. "
    "When adding instruments to a watch list, use add_watch_list_instrument which enqueues a job to fetch "
    "the contract directly from IBKR. Then use check_watchlist_job to poll for the result. "
    "Keep responses concise and operator-focused."
)
_MAX_MESSAGES = 16
_MAX_TOOL_STEPS = 8
_DEFAULT_LLM_MODEL = os.getenv("TRADEBOT_LLM_MODEL") or "gpt-5-mini"
_DEFAULT_LLM_BASE_URL = os.getenv("TRADEBOT_LLM_BASE_URL") or "https://api.openai.com/v1"
_DEFAULT_TIMEOUT_SECONDS = 45
_TOOL_SOURCE = "tradebot-llm"

_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_accounts",
            "description": "List available brokerage accounts for order routing.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_positions",
            "description": "Read current positions from the database.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 25,
                    }
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_jobs",
            "description": "Read latest job queue records.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 20,
                    },
                    "include_archived": {
                        "type": "boolean",
                        "default": False,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_orders",
            "description": "Read latest order records and optional recent events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 200,
                        "default": 20,
                    },
                    "status": {"type": "string"},
                    "include_events": {
                        "type": "boolean",
                        "default": True,
                    },
                    "events_per_order": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 20,
                        "default": 3,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enqueue_positions_sync_job",
            "description": "Enqueue a positions.sync job for worker:jobs to process.",
            "parameters": {
                "type": "object",
                "properties": {
                    "request_text": {"type": "string"},
                    "max_attempts": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 3,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enqueue_contracts_sync_job",
            "description": (
                "Enqueue a contracts.sync job to fetch available contracts from IBKR into the database. "
                "Pass symbol and sec_type to sync a specific instrument (e.g. NQ FUT, AAPL STK). "
                "Defaults to CL FUT if not specified."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol, e.g. CL, ES, NQ, AAPL",
                    },
                    "sec_type": {
                        "type": "string",
                        "enum": ["FUT", "OPT", "FOP", "STK"],
                        "description": "Security type to sync",
                    },
                    "request_text": {"type": "string"},
                    "max_attempts": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "default": 3,
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_contract",
            "description": (
                "Read-only lookup of contract details from the database. "
                "Use this for informational queries like 'what is the front month for CL?' "
                "or 'what NQ contracts are available?'. This is read-only and has no side effects."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol, e.g. CL, ES, NQ, AAPL",
                    },
                    "sec_type": {
                        "type": "string",
                        "enum": ["FUT", "OPT", "FOP", "STK"],
                    },
                    "contract_month": {
                        "type": "string",
                        "description": "YYYY-MM or month name like 'March 2026'",
                    },
                    "strike": {
                        "type": "number",
                        "description": "Strike price for OPT/FOP",
                    },
                    "right": {
                        "type": "string",
                        "enum": ["C", "P"],
                        "description": "Call or Put for OPT/FOP",
                    },
                },
                "required": ["symbol", "sec_type"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_watch_lists",
            "description": "List all watch lists with instrument counts.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_watch_list",
            "description": "Create a new watch list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the watch list",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional description",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_watch_list",
            "description": "Get a watch list with all its instruments.",
            "parameters": {
                "type": "object",
                "properties": {
                    "watch_list_id": {
                        "type": "integer",
                        "description": "ID of the watch list",
                    },
                },
                "required": ["watch_list_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_watch_list_instrument",
            "description": (
                "Add an instrument to a watch list by fetching its contract from IBKR. "
                "Enqueues a background job that connects to IBKR, fetches the single contract, "
                "upserts it into contract_refs, and adds it to the watch list. "
                "Returns a job_id — use check_watchlist_job to poll for the result."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "watch_list_id": {
                        "type": "integer",
                        "description": "ID of the watch list to add to",
                    },
                    "symbol": {
                        "type": "string",
                        "description": "Ticker symbol, e.g. CL, ES, AAPL",
                    },
                    "sec_type": {
                        "type": "string",
                        "enum": ["STK", "FUT", "OPT", "FOP"],
                        "description": "Security type",
                    },
                    "contract_month": {
                        "type": "string",
                        "description": "YYYY-MM or month name like 'April 2026'",
                    },
                    "strike": {
                        "type": "number",
                        "description": "Strike price for OPT/FOP",
                    },
                    "right": {
                        "type": "string",
                        "enum": ["C", "P"],
                        "description": "Call or Put for OPT/FOP",
                    },
                },
                "required": ["watch_list_id", "symbol", "sec_type"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_watch_list_instrument",
            "description": "Remove an instrument from a watch list.",
            "parameters": {
                "type": "object",
                "properties": {
                    "watch_list_id": {
                        "type": "integer",
                        "description": "ID of the watch list",
                    },
                    "instrument_id": {
                        "type": "integer",
                        "description": "ID of the instrument to remove",
                    },
                },
                "required": ["watch_list_id", "instrument_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_watchlist_job",
            "description": (
                "Poll a watchlist.add_instrument job for its result. "
                "Returns instrument details when completed, error when failed, "
                "or a 'still running' message if not yet done. Call again if still running."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "integer",
                        "description": "The job ID returned by add_watch_list_instrument",
                    },
                },
                "required": ["job_id"],
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class ChatInputMessage:
    role: str
    text: str


@dataclass(frozen=True)
class _TradebotModelConfig:
    api_key: str
    base_url: str
    model: str
    timeout_seconds: int


class _GraphState(TypedDict):
    session: Session
    latest_user_text: str
    config: _TradebotModelConfig
    llm_messages: list[dict[str, Any]]
    completion: dict[str, Any] | None
    final_text: str | None
    tool_iterations: int


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _extract_latest_user_text(messages: Sequence[ChatInputMessage]) -> str:
    for message in reversed(messages):
        if message.role == "user" and message.text.strip():
            return message.text.strip()
    raise ValueError("No user message found")


def _normalize_chat_role(role: str) -> str:
    lowered = role.lower().strip()
    if lowered == "assistant":
        return "assistant"
    return "user"


def _coerce_int_arg(
    args: dict[str, Any],
    key: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = args.get(key, default)
    if not isinstance(raw, int):
        raise ValueError(f"'{key}' must be an integer.")
    if raw < minimum or raw > maximum:
        raise ValueError(f"'{key}' must be between {minimum} and {maximum}.")
    return raw


def _coerce_bool_arg(args: dict[str, Any], key: str, default: bool) -> bool:
    raw = args.get(key, default)
    if not isinstance(raw, bool):
        raise ValueError(f"'{key}' must be a boolean.")
    return raw


def _coerce_optional_str_arg(args: dict[str, Any], key: str) -> str | None:
    raw = args.get(key)
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"'{key}' must be a string.")
    value = raw.strip()
    return value or None


def _tool_list_accounts(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    if args:
        raise ValueError("list_accounts does not take arguments.")
    rows = session.execute(select(Account).order_by(Account.id)).scalars().all()
    return {
        "accounts": [
            {
                "id": account.id,
                "alias": account.alias,
                "masked_account": mask_ibkr_account(account.account),
            }
            for account in rows
        ]
    }


def _tool_list_positions(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    limit = _coerce_int_arg(args, "limit", 25, 1, 200)
    stmt = select(Position, Account).outerjoin(Account, Position.account_id == Account.id).order_by(func.abs(Position.position).desc()).limit(limit)
    rows = session.execute(stmt).all()
    positions = []
    for position, account in rows:
        account_alias = account.alias if account and account.alias else None
        positions.append(
            {
                "id": position.id,
                "account_id": position.account_id,
                "account_alias": account_alias,
                "symbol": position.symbol,
                "sec_type": position.sec_type,
                "position": position.position,
                "avg_cost": position.avg_cost,
                "local_symbol": position.local_symbol,
                "fetched_at": _iso(position.fetched_at),
            }
        )
    return {"positions": positions, "count": len(positions)}


def _tool_list_jobs(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    limit = _coerce_int_arg(args, "limit", 20, 1, 200)
    include_archived = _coerce_bool_arg(args, "include_archived", False)
    stmt = select(Job)
    if not include_archived:
        stmt = stmt.where(Job.archived_at.is_(None))
    rows = session.execute(stmt.order_by(Job.created_at.desc()).limit(limit)).scalars().all()
    jobs = [
        {
            "id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "attempts": job.attempts,
            "max_attempts": job.max_attempts,
            "last_error": job.last_error,
            "available_at": _iso(job.available_at),
            "started_at": _iso(job.started_at),
            "completed_at": _iso(job.completed_at),
            "created_at": _iso(job.created_at),
            "updated_at": _iso(job.updated_at),
        }
        for job in rows
    ]
    return {"jobs": jobs, "count": len(jobs)}


def _tool_list_orders(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    limit = _coerce_int_arg(args, "limit", 20, 1, 200)
    include_events = _coerce_bool_arg(args, "include_events", True)
    events_per_order = _coerce_int_arg(args, "events_per_order", 3, 1, 20)
    status = _coerce_optional_str_arg(args, "status")

    stmt = select(Order, Account).outerjoin(Account, Order.account_id == Account.id).order_by(Order.created_at.desc())
    if status is not None:
        stmt = stmt.where(func.lower(Order.status) == status.lower())
    rows = session.execute(stmt.limit(limit)).all()

    orders: list[dict[str, Any]] = []
    for order, account in rows:
        row = {
            "id": order.id,
            "account_id": order.account_id,
            "account_alias": account.alias if account else None,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "status": order.status,
            "filled_quantity": order.filled_quantity,
            "avg_fill_price": order.avg_fill_price,
            "contract_month": order.contract_month,
            "local_symbol": order.local_symbol,
            "ib_order_id": order.ib_order_id,
            "ib_perm_id": order.ib_perm_id,
            "last_error": order.last_error,
            "created_at": _iso(order.created_at),
            "submitted_at": _iso(order.submitted_at),
            "completed_at": _iso(order.completed_at),
            "updated_at": _iso(order.updated_at),
        }
        if include_events:
            events = (
                session.execute(select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.created_at.desc()).limit(events_per_order))
                .scalars()
                .all()
            )
            row["events"] = [
                {
                    "event_type": event.event_type,
                    "message": event.message,
                    "status": event.status,
                    "filled_quantity": event.filled_quantity,
                    "avg_fill_price": event.avg_fill_price,
                    "created_at": _iso(event.created_at),
                }
                for event in events
            ]
        orders.append(row)

    return {"orders": orders, "count": len(orders)}


def _tool_enqueue_positions_sync_job(session: Session, latest_user_text: str, args: dict[str, Any]) -> dict[str, Any]:
    max_attempts = _coerce_int_arg(args, "max_attempts", 3, 1, 10)
    request_text = _coerce_optional_str_arg(args, "request_text") or latest_user_text
    job = enqueue_job(
        session=session,
        job_type=JOB_TYPE_POSITIONS_SYNC,
        payload={},
        source=_TOOL_SOURCE,
        request_text=request_text,
        max_attempts=max_attempts,
    )
    session.commit()
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "max_attempts": job.max_attempts,
    }


_FUTURES_EXCHANGE_MAP: dict[str, str] = {
    "CL": "NYMEX",
    "MCL": "NYMEX",
    "NG": "NYMEX",
    "HO": "NYMEX",
    "RB": "NYMEX",
    "ES": "CME",
    "MES": "CME",
    "NQ": "CME",
    "MNQ": "CME",
    "RTY": "CME",
    "M2K": "CME",
    "YM": "CBOT",
    "MYM": "CBOT",
    "ZB": "CBOT",
    "ZN": "CBOT",
    "ZF": "CBOT",
    "ZT": "CBOT",
    "ZC": "CBOT",
    "ZS": "CBOT",
    "ZW": "CBOT",
    "GC": "COMEX",
    "MGC": "COMEX",
    "SI": "COMEX",
    "SIL": "COMEX",
    "HG": "COMEX",
}


def _resolve_exchange(symbol: str, sec_type: str) -> str:
    """Resolve exchange for a symbol. Returns exchange or raises if unknown futures symbol."""
    if sec_type in ("FUT", "FOP"):
        exchange = _FUTURES_EXCHANGE_MAP.get(symbol)
        if exchange is None:
            known = ", ".join(sorted(_FUTURES_EXCHANGE_MAP.keys()))
            raise ValueError(f"Unknown exchange for futures symbol '{symbol}'. " f"Known symbols: {known}. " f"Please tell me which exchange this trades on.")
        return exchange
    if sec_type == "OPT":
        return "SMART"
    # STK
    return "SMART"


def _tool_enqueue_contracts_sync_job(session: Session, latest_user_text: str, args: dict[str, Any]) -> dict[str, Any]:
    max_attempts = _coerce_int_arg(args, "max_attempts", 3, 1, 10)
    request_text = _coerce_optional_str_arg(args, "request_text") or latest_user_text

    symbol = _coerce_optional_str_arg(args, "symbol")
    sec_type = _coerce_optional_str_arg(args, "sec_type")

    payload: dict[str, Any] = {}
    if symbol is not None or sec_type is not None:
        sym = (symbol or "CL").upper()
        st = (sec_type or "FUT").upper()
        exchange = _resolve_exchange(sym, st)
        payload["specs"] = [{"symbol": sym, "sec_type": st, "exchange": exchange}]

    job = enqueue_job(
        session=session,
        job_type=JOB_TYPE_CONTRACTS_SYNC,
        payload=payload,
        source=_TOOL_SOURCE,
        request_text=request_text,
        max_attempts=max_attempts,
    )
    session.commit()
    return {
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "max_attempts": job.max_attempts,
    }


def _tool_lookup_contract(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    symbol_raw = args.get("symbol")
    if not isinstance(symbol_raw, str) or not symbol_raw.strip():
        raise ValueError("'symbol' must be a non-empty string.")
    symbol = symbol_raw.strip().upper()

    sec_type_raw = args.get("sec_type")
    if not isinstance(sec_type_raw, str) or not sec_type_raw.strip():
        raise ValueError("'sec_type' must be a non-empty string.")
    sec_type = sec_type_raw.strip().upper()

    requested_contract_month_raw = _coerce_optional_str_arg(args, "contract_month")
    requested_contract_month = normalize_contract_month_input(requested_contract_month_raw)

    strike_raw = args.get("strike")
    strike = float(strike_raw) if strike_raw is not None else None
    right = _coerce_optional_str_arg(args, "right")
    if right is not None:
        right = right.upper()

    min_days_to_expiry = get_int_env("BROKER_CL_MIN_DAYS_TO_EXPIRY", DEFAULT_CL_MIN_DAYS_TO_EXPIRY)

    contracts = find_contracts(
        session=session,
        symbol=symbol,
        sec_type=sec_type,
        contract_month=requested_contract_month,
        min_days_to_expiry=min_days_to_expiry,
        strike=strike,
        right=right,
    )

    # Group by month for summary
    months: dict[str, dict[str, Any]] = {}
    for c in contracts:
        month = c.get("contract_month") or "unknown"
        if month not in months:
            months[month] = {
                "contract_month": month,
                "contract_month_display": (display_contract_month(month) if month != "unknown" else "unknown"),
                "con_id": c["con_id"],
                "local_symbol": c["local_symbol"],
                "exchange": c["exchange"],
                "contract_expiry": c["contract_expiry"],
                "days_to_expiry": c["days_to_expiry"],
                "trading_class": c["trading_class"],
                "multiplier": c["multiplier"],
            }

    front_month = contracts[0] if contracts else None

    return {
        "symbol": symbol,
        "sec_type": sec_type,
        "total_contracts": len(contracts),
        "available_months": [months[m] for m in months],
        "front_month": (
            {
                "contract_month": front_month["contract_month"],
                "contract_month_display": (display_contract_month(front_month["contract_month"]) if front_month.get("contract_month") else "unknown"),
                "con_id": front_month["con_id"],
                "local_symbol": front_month["local_symbol"],
                "contract_expiry": front_month["contract_expiry"],
                "days_to_expiry": front_month["days_to_expiry"],
            }
            if front_month
            else None
        ),
    }


def _tool_list_watch_lists(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    count_subq = select(func.count(WatchListInstrument.id)).where(WatchListInstrument.watch_list_id == WatchList.id).correlate(WatchList).scalar_subquery()
    stmt = select(WatchList, count_subq).order_by(WatchList.created_at.desc())
    rows = session.execute(stmt).all()
    return {
        "watch_lists": [
            {
                "id": wl.id,
                "name": wl.name,
                "description": wl.description,
                "instrument_count": count,
            }
            for wl, count in rows
        ]
    }


def _tool_create_watch_list(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    name = args.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("'name' must be a non-empty string.")
    description = _coerce_optional_str_arg(args, "description")
    wl = WatchList(name=name.strip(), description=description)
    session.add(wl)
    session.commit()
    session.refresh(wl)
    return {"id": wl.id, "name": wl.name, "description": wl.description}


def _tool_get_watch_list(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    wl_id = args.get("watch_list_id")
    if not isinstance(wl_id, int):
        raise ValueError("'watch_list_id' must be an integer.")
    wl = session.get(WatchList, wl_id)
    if wl is None:
        raise ValueError(f"Watch list #{wl_id} not found.")
    instruments = (
        session.execute(select(WatchListInstrument).where(WatchListInstrument.watch_list_id == wl_id).order_by(WatchListInstrument.created_at)).scalars().all()
    )
    return {
        "id": wl.id,
        "name": wl.name,
        "description": wl.description,
        "instruments": [
            {
                "id": inst.id,
                "con_id": inst.con_id,
                "symbol": inst.symbol,
                "sec_type": inst.sec_type,
                "exchange": inst.exchange,
                "local_symbol": inst.local_symbol,
                "contract_month": inst.contract_month,
                "contract_expiry": inst.contract_expiry,
                "strike": inst.strike,
                "right": inst.right,
            }
            for inst in instruments
        ],
    }


def _tool_add_watch_list_instrument(session: Session, latest_user_text: str, args: dict[str, Any]) -> dict[str, Any]:
    wl_id = args.get("watch_list_id")
    if not isinstance(wl_id, int):
        raise ValueError("'watch_list_id' must be an integer.")
    wl = session.get(WatchList, wl_id)
    if wl is None:
        raise ValueError(f"Watch list #{wl_id} not found.")

    symbol_raw = args.get("symbol")
    if not isinstance(symbol_raw, str) or not symbol_raw.strip():
        raise ValueError("'symbol' must be a non-empty string.")
    symbol = symbol_raw.strip().upper()

    sec_type_raw = args.get("sec_type")
    if not isinstance(sec_type_raw, str) or not sec_type_raw.strip():
        raise ValueError("'sec_type' must be a non-empty string.")
    sec_type = sec_type_raw.strip().upper()
    if sec_type not in {"STK", "FUT", "OPT", "FOP"}:
        raise ValueError("'sec_type' must be one of STK, FUT, OPT, FOP.")

    requested_contract_month_raw = _coerce_optional_str_arg(args, "contract_month")
    requested_contract_month = normalize_contract_month_input(requested_contract_month_raw)

    strike_raw = args.get("strike")
    strike = float(strike_raw) if strike_raw is not None else None
    right = _coerce_optional_str_arg(args, "right")
    if right is not None:
        right = right.upper()

    exchange = _resolve_exchange(symbol, sec_type)

    payload: dict[str, Any] = {
        "watch_list_id": wl_id,
        "symbol": symbol,
        "sec_type": sec_type,
        "exchange": exchange,
    }
    if requested_contract_month is not None:
        payload["contract_month"] = requested_contract_month
    if strike is not None:
        payload["strike"] = strike
    if right is not None:
        payload["right"] = right

    job = enqueue_job(
        session=session,
        job_type=JOB_TYPE_WATCHLIST_ADD_INSTRUMENT,
        payload=payload,
        source=_TOOL_SOURCE,
        request_text=latest_user_text,
    )
    session.commit()
    return {
        "job_id": job.id,
        "status": job.status,
        "message": (f"Enqueued job to fetch {symbol} {sec_type} from IBKR and add to watch list #{wl_id}. " "Use check_watchlist_job to poll for the result."),
    }


def _tool_check_watchlist_job(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    job_id = args.get("job_id")
    if not isinstance(job_id, int):
        raise ValueError("'job_id' must be an integer.")

    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job #{job_id} not found.")
    if job.job_type != JOB_TYPE_WATCHLIST_ADD_INSTRUMENT:
        raise ValueError(f"Job #{job_id} is not a watchlist.add_instrument job " f"(it is '{job.job_type}').")

    if job.status == "completed":
        return {
            "status": "completed",
            "result": job.result,
        }
    elif job.status == "failed":
        return {
            "status": "failed",
            "error": job.last_error,
        }
    else:
        return {
            "status": job.status,
            "message": "Job is still running. Call check_watchlist_job again shortly.",
        }


def _tool_remove_watch_list_instrument(session: Session, _: str, args: dict[str, Any]) -> dict[str, Any]:
    wl_id = args.get("watch_list_id")
    if not isinstance(wl_id, int):
        raise ValueError("'watch_list_id' must be an integer.")
    inst_id = args.get("instrument_id")
    if not isinstance(inst_id, int):
        raise ValueError("'instrument_id' must be an integer.")

    inst = (
        session.execute(
            select(WatchListInstrument).where(
                WatchListInstrument.id == inst_id,
                WatchListInstrument.watch_list_id == wl_id,
            )
        )
        .scalars()
        .first()
    )
    if inst is None:
        raise ValueError(f"Instrument #{inst_id} not found in watch list #{wl_id}.")
    session.delete(inst)
    session.commit()
    return {"ok": True}


_TOOL_HANDLERS = {
    "list_accounts": _tool_list_accounts,
    "list_positions": _tool_list_positions,
    "list_jobs": _tool_list_jobs,
    "list_orders": _tool_list_orders,
    "enqueue_positions_sync_job": _tool_enqueue_positions_sync_job,
    "enqueue_contracts_sync_job": _tool_enqueue_contracts_sync_job,
    "lookup_contract": _tool_lookup_contract,
    "list_watch_lists": _tool_list_watch_lists,
    "create_watch_list": _tool_create_watch_list,
    "get_watch_list": _tool_get_watch_list,
    "add_watch_list_instrument": _tool_add_watch_list_instrument,
    "remove_watch_list_instrument": _tool_remove_watch_list_instrument,
    "check_watchlist_job": _tool_check_watchlist_job,
}


def _load_model_config() -> _TradebotModelConfig:
    api_key = get_str_env("TRADEBOT_LLM_API_KEY") or get_str_env("OPENAI_API_KEY")
    if api_key is None:
        raise ValueError("Missing TRADEBOT_LLM_API_KEY (or OPENAI_API_KEY).")

    base_url = get_str_env("TRADEBOT_LLM_BASE_URL", _DEFAULT_LLM_BASE_URL)
    model = get_str_env("TRADEBOT_LLM_MODEL", _DEFAULT_LLM_MODEL)
    timeout_seconds = get_int_env("TRADEBOT_LLM_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)
    return _TradebotModelConfig(
        api_key=api_key,
        base_url=base_url.rstrip("/"),
        model=model,
        timeout_seconds=timeout_seconds,
    )


def _call_llm(
    config: _TradebotModelConfig,
    messages: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "model": config.model,
        "messages": messages,
        "tools": _TOOL_SPECS,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }

    endpoint = f"{config.base_url}/chat/completions"
    parsed_endpoint = parse.urlparse(endpoint)
    if parsed_endpoint.scheme not in {"http", "https"}:
        raise ValueError("TRADEBOT_LLM_BASE_URL must use http or https (for example: https://api.openai.com/v1).")
    if not parsed_endpoint.netloc:
        raise ValueError("TRADEBOT_LLM_BASE_URL must include a network host.")
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=config.timeout_seconds) as response:  # noqa: S310  # nosec B310
            raw = response.read().decode("utf-8")
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Tradebot LLM HTTP {exc.code}: {details}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Tradebot LLM request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Tradebot LLM returned a non-JSON response.") from exc
    return parsed


def _execute_tool_call(
    session: Session,
    latest_user_text: str,
    tool_name: str,
    arguments_json: str,
) -> dict[str, Any]:
    handler = _TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return {"ok": False, "error": f"Unknown tool '{tool_name}'."}

    try:
        args_obj = json.loads(arguments_json) if arguments_json.strip() else {}
    except json.JSONDecodeError:
        return {
            "ok": False,
            "error": f"Arguments for tool '{tool_name}' were not valid JSON.",
        }

    if not isinstance(args_obj, dict):
        return {
            "ok": False,
            "error": f"Arguments for tool '{tool_name}' must be an object.",
        }

    try:
        return {"ok": True, "result": handler(session, latest_user_text, args_obj)}
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        return {"ok": False, "error": str(exc)}


def _extract_assistant_message(completion: dict[str, Any]) -> dict[str, Any]:
    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Tradebot LLM response did not include any choices.")

    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Tradebot LLM response had an invalid message payload.")

    return message


def _model_node(state: _GraphState) -> _GraphState:
    completion = _call_llm(state["config"], state["llm_messages"])
    assistant_message = _extract_assistant_message(completion)
    assistant_text_raw = assistant_message.get("content")
    assistant_text = assistant_text_raw if isinstance(assistant_text_raw, str) else ""
    tool_calls = assistant_message.get("tool_calls")

    assistant_history_message: dict[str, Any] = {
        "role": "assistant",
        "content": assistant_text,
    }
    if isinstance(tool_calls, list) and tool_calls:
        assistant_history_message["tool_calls"] = tool_calls

    next_llm_messages = [
        *state["llm_messages"],
        assistant_history_message,
    ]

    if not isinstance(tool_calls, list) or not tool_calls:
        final_text = assistant_text.strip() or ("I could not complete that request with confidence. " "Please retry with a more specific instruction.")
        return {
            **state,
            "completion": completion,
            "llm_messages": next_llm_messages,
            "final_text": final_text,
        }

    return {
        **state,
        "completion": completion,
        "llm_messages": next_llm_messages,
    }


def _tools_node(state: _GraphState) -> _GraphState:
    completion = state["completion"]
    if completion is None:
        return {
            **state,
            "final_text": ("I could not complete that request with confidence. " "Please retry with a more specific instruction."),
        }

    assistant_message = _extract_assistant_message(completion)
    tool_calls = assistant_message.get("tool_calls")
    if not isinstance(tool_calls, list) or not tool_calls:
        return state

    next_llm_messages = list(state["llm_messages"])
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        call_id = call.get("id")
        function_payload = call.get("function")
        if not isinstance(call_id, str) or not isinstance(function_payload, dict):
            continue

        tool_name = function_payload.get("name")
        arguments_raw = function_payload.get("arguments")
        if not isinstance(tool_name, str):
            continue
        arguments_json = arguments_raw if isinstance(arguments_raw, str) else "{}"

        result = _execute_tool_call(
            session=state["session"],
            latest_user_text=state["latest_user_text"],
            tool_name=tool_name,
            arguments_json=arguments_json,
        )
        next_llm_messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(result),
            }
        )

    return {
        **state,
        "llm_messages": next_llm_messages,
        "tool_iterations": state["tool_iterations"] + 1,
    }


def _tool_limit_node(state: _GraphState) -> _GraphState:
    return {
        **state,
        "final_text": ("I reached the maximum number of tool steps for this request. " "Please retry with a more specific instruction."),
    }


def _route_after_model(state: _GraphState) -> str:
    if state.get("final_text"):
        return "done"

    completion = state.get("completion")
    if completion is None:
        return "limit"

    message = _extract_assistant_message(completion)
    tool_calls = message.get("tool_calls")
    has_tool_calls = isinstance(tool_calls, list) and bool(tool_calls)
    if not has_tool_calls:
        return "done"

    if state["tool_iterations"] >= _MAX_TOOL_STEPS:
        return "limit"
    return "tools"


def _build_graph() -> Any:
    graph = StateGraph(_GraphState)
    graph.add_node("model", _model_node)
    graph.add_node("tools", _tools_node)
    graph.add_node("tool_limit", _tool_limit_node)
    graph.add_edge(START, "model")
    graph.add_conditional_edges(
        "model",
        _route_after_model,
        {
            "tools": "tools",
            "done": END,
            "limit": "tool_limit",
        },
    )
    graph.add_edge("tools", "model")
    graph.add_edge("tool_limit", END)
    return graph.compile()


_GRAPH_APP = _build_graph()


def run_tradebot_agent(session: Session, messages: Sequence[ChatInputMessage]) -> str:
    if not messages:
        raise ValueError("No chat messages provided.")

    latest_user_text = _extract_latest_user_text(messages)
    config = _load_model_config()

    llm_messages: list[dict[str, Any]] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    for message in list(messages)[-_MAX_MESSAGES:]:
        cleaned_text = message.text.strip()
        if not cleaned_text:
            continue
        llm_messages.append(
            {
                "role": _normalize_chat_role(message.role),
                "content": cleaned_text,
            }
        )

    initial_state: _GraphState = {
        "session": session,
        "latest_user_text": latest_user_text,
        "config": config,
        "llm_messages": llm_messages,
        "completion": None,
        "final_text": None,
        "tool_iterations": 0,
    }
    final_state = _GRAPH_APP.invoke(initial_state)
    final_text = final_state.get("final_text")
    if isinstance(final_text, str) and final_text.strip():
        return final_text.strip()

    return "I could not complete that request with confidence. " "Please retry with a more specific instruction."
