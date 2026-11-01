# BOUNDARY: This module must NEVER import ib_async or make direct broker connections.
# All IB interactions happen through API/DB mutations and worker processes.

"""LLM-backed tradebot agent with LangGraph tool workflows."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Sequence, TypedDict, TypeVar
from urllib import error, parse, request

from langgraph.graph import END, START, StateGraph
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, ValidationInfo, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.data.exchanges import resolve_exchange as _resolve_exchange
from src.domain.enums import JobStatus
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
from src.services.contract_lookup import ContractLookup, find_contracts_with_fallback
from src.services.jobs import (
    JOB_TYPE_CONTRACTS_SYNC,
    JOB_TYPE_MARKET_DATA_SNAPSHOT,
    JOB_TYPE_ORDER_FETCH_SYNC,
    JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
    JOB_TYPE_WATCHLIST_ADD_INSTRUMENT,
    enqueue_job,
)
from src.services.order_mutations import (
    OrderCreateInput,
    normalize_order_create_input,
)
from src.services.semantic.executor import run_metric_query
from src.services.semantic.loader import get_model
from src.services.semantic.resolver import ALLOWED_TIME_GRAINS, build_metric_query
from src.services.trade_group_pnl import compute_trade_group_pnl, resolve_trade_group
from src.utils.env_vars import get_int_env, get_str_env
from src.utils.ibkr_account import mask_ibkr_account

logger = logging.getLogger("tradebot_agent")

_SYSTEM_PROMPT = (
    "You are Tradebot, an operations assistant for a live trading desk. "
    "Use tools for factual data access and side effects. "
    "Never fabricate DB data, job IDs, order IDs, fills, or statuses. "
    "When a user asks for current state, call read tools first. "
    "You can enqueue positions sync jobs, contracts sync jobs, and order fetch/sync jobs. "
    "For informational queries about contracts (front month, available months, contract details), use lookup_contract. "
    "To see which products are actively maintained in the security master and their exchanges, use list_activated_products. "
    "lookup_contract checks the database first; if no contracts exist, it queues a contracts sync job and returns pending_job_id "
    "instead of contracts, so tell the user to check back shortly and repeat the lookup. "
    "For options (FOP/OPT), use contract_expiry (YYYY-MM-DD) to find a specific weekly expiry rather than contract_month. "
    "When the user says 'next Friday' or a specific date, convert it to contract_expiry format. "
    "You can preview orders via preview_order. "
    "There is no cancel tool in chat; advise using the Orders API/UI cancel action when needed. "
    "You can also manage watch lists: create watch lists, add instruments to them, list them, and remove instruments. "
    "add_watch_list_instrument finds the contract in the DB, adds it to the watch list, "
    "and enqueues a market data job for latest prices. It returns immediately — no need to poll. "
    "If the contract is not in the DB yet it queues a contracts sync job and returns pending_job_id without adding anything; "
    "tell the user to check back shortly and repeat the request. "
    "For analytics questions about realized PnL, win rate, or trade counts (e.g. 'PnL by symbol this quarter', "
    "'win rate last month'), use query_metric: it runs business-analyst metric definitions from the semantic "
    "model as read-only SQL. Pick a metric and dimensions by name — do not ask for raw SQL. "
    "For the realized and unrealized PnL of one specific trade group (the trade group detail figures, including "
    "live/intraday PnL), use trade_group_pnl with the group name or id. "
    "Keep responses concise and operator-focused."
)
_MAX_MESSAGES = 16
_MAX_TOOL_STEPS = 8
_DEFAULT_LLM_MODEL = os.getenv("TRADEBOT_LLM_MODEL") or "gpt-5-mini"
_DEFAULT_LLM_BASE_URL = os.getenv("TRADEBOT_LLM_BASE_URL") or "https://api.openai.com/v1"
_DEFAULT_TIMEOUT_SECONDS = 45
_TOOL_SOURCE = "tradebot-llm"

# --- Tool registry -------------------------------------------------------------------------------
# A ``Tool`` is one LLM-callable function: its name, description, a Pydantic ``Args`` model (the
# validator and the source of the JSON schema), and the function that runs it. ``TOOLS`` is the only
# list; ``_TOOL_SPECS`` (sent to the LLM) and ``_TOOL_HANDLERS`` (used to dispatch) are both derived
# from it at the bottom of the tool section, so they cannot drift.

# The third argument is the validated ``Args`` instance; ``Any`` because each tool has its own model.
ToolRun = Callable[[Session, str, Any], dict[str, Any]]
_ArgsT = TypeVar("_ArgsT", bound=BaseModel)


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    args: type[BaseModel]
    run: ToolRun
    # Explicit JSON schema for ``parameters``; only for a tool whose enums come from data at import time.
    parameters: dict[str, Any] | None = None

    def spec(self) -> dict[str, Any]:
        parameters = self.parameters if self.parameters is not None else _parameters_schema(self.args)
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": parameters},
        }


TOOLS: list[Tool] = []


def _register_tool(new_tool: Tool) -> None:
    if any(existing.name == new_tool.name for existing in TOOLS):
        raise ValueError(f"Duplicate tradebot tool '{new_tool.name}'.")
    TOOLS.append(new_tool)


def tool(
    name: str,
    description: str,
    args: type[_ArgsT],
) -> Callable[[Callable[[Session, str, _ArgsT], dict[str, Any]]], Callable[[Session, str, _ArgsT], dict[str, Any]]]:
    """Register the decorated function as the handler of tool ``name``, validated through ``args``."""

    def register(run: Callable[[Session, str, _ArgsT], dict[str, Any]]) -> Callable[[Session, str, _ArgsT], dict[str, Any]]:
        _register_tool(Tool(name=name, description=description, args=args, run=run))
        return run

    return register


def _fold_any_of(node: dict[str, Any]) -> dict[str, Any]:
    """``X | None`` becomes ``X``; ``str | int`` becomes ``type: [string, integer]``."""
    rest = {key: value for key, value in node.items() if key != "anyOf"}
    non_null = [member for member in node["anyOf"] if member != {"type": "null"}]
    if len(non_null) == 1:
        return {**non_null[0], **rest}
    return {**rest, "type": [member["type"] for member in non_null]}


def _clean_schema(node: Any) -> Any:
    """Reduce a Pydantic JSON schema to the plain shape the tool specs have always had.

    Drops generated ``title``s and ``default: null``, and folds ``anyOf`` unions into a plain schema.
    """
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    if not isinstance(node, dict):
        return node

    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if (key == "title" and isinstance(value, str)) or (key == "default" and value is None):
            continue
        # Keys under "properties" are argument names, not schema keywords.
        cleaned[key] = {name: _clean_schema(sub) for name, sub in value.items()} if key == "properties" else _clean_schema(value)
    return _fold_any_of(cleaned) if "anyOf" in cleaned else cleaned


def _parameters_schema(args: type[BaseModel]) -> dict[str, Any]:
    schema: dict[str, Any] = _clean_schema(args.model_json_schema())
    schema.pop("description", None)  # the model's docstring, not part of the tool's parameters
    return schema


class _ToolArgs(BaseModel):
    """Base for tool arguments.

    Types are strict (the string ``"5"`` is not an integer). Unknown keys are ignored, as the old
    hand-rolled parsing did, while the published schema keeps ``additionalProperties: false``.
    """

    model_config = ConfigDict(strict=True, extra="ignore", json_schema_extra={"additionalProperties": False})


class _NoArgs(_ToolArgs):
    """A tool that takes no arguments and rejects any it is given."""

    model_config = ConfigDict(extra="forbid")


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string.")
    return value


def _strip_non_blank(value: str) -> str:
    return _require_non_blank(value).strip()


def _group_not_blank(value: str | int) -> str | int:
    if isinstance(value, str):
        _require_non_blank(value)
    return value


OptStr = Annotated[str | None, AfterValidator(_strip_or_none)]  # surrounding whitespace removed, blank means absent
NonBlankStr = Annotated[str, AfterValidator(_strip_non_blank)]  # required, stripped


def _format_validation_error(tool_name: str, exc: ValidationError) -> str:
    problems = []
    for err in exc.errors():
        where = ".".join(str(part) for part in err["loc"])
        message = err["msg"].removeprefix("Value error, ")
        problems.append(f"'{where}': {message}" if where else message)
    return f"Invalid arguments for tool '{tool_name}': " + "; ".join(problems)


_NUMERIC_FILTER_DIMS = {"strike"}


def _build_query_metric_schema() -> tuple[str, dict[str, Any]]:
    """Build the query_metric description and JSON schema from the OSI semantic model.

    The metric/dimension enums come straight from the model so the LLM can only
    reference defined names — this is the safety boundary that replaces free-form
    SQL. Not every dimension is valid for every metric (grain rules): the
    resolver rejects out-of-grain combinations with a message naming the valid
    options, so the model self-corrects. Raises if the model can't be loaded; the
    caller decides whether to skip the tool rather than break the whole agent.
    """
    model = get_model()
    metric_names = list(model.metrics)
    dim_names = model.all_dimension_names()
    filter_props: dict[str, Any] = {name: {"type": "number" if name in _NUMERIC_FILTER_DIMS else "string"} for name in model.filterable_dimension_names()}

    metric_blurb = "; ".join((f"{m.name} [grain: {m.fact}]" + (f" — {m.description.strip()}" if m.description else "")) for m in model.metrics.values())

    description = (
        "Run a business-analyst metric query over the trade database using the OSI semantic model. "
        "You pick a metric and dimensions by name; the server compiles them into read-only SQL. "
        "You cannot and need not write SQL. Not all dimensions apply to all metrics — if one is "
        "out of grain the tool returns an error naming the valid options; retry with those. "
        f"Metrics — {metric_blurb}. "
        f"Group-by / filter dimensions — {', '.join(dim_names)}."
    )
    parameters = {
        "type": "object",
        "properties": {
            "metric": {"type": "string", "enum": metric_names},
            "group_by": {
                "type": "array",
                "items": {"type": "string", "enum": dim_names},
                "description": "Dimensions to group the metric by.",
            },
            "filters": {
                "type": "object",
                "properties": filter_props,
                "additionalProperties": False,
                "description": "Equality filters keyed by dimension name.",
            },
            "start_date": {
                "type": "string",
                "description": "ISO lower bound (inclusive) on executed_at, e.g. '2026-01-01'.",
            },
            "end_date": {
                "type": "string",
                "description": "ISO upper bound (inclusive) on executed_at.",
            },
            "time_grain": {
                "type": "string",
                "enum": list(ALLOWED_TIME_GRAINS),
                "description": "Bucket the executed_at time dimension when grouping by it.",
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 50},
        },
        "required": ["metric"],
        "additionalProperties": False,
    }
    return description, parameters


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


@tool("list_accounts", "List available brokerage accounts for order routing.", _NoArgs)
def _tool_list_accounts(session: Session, _: str, args: _NoArgs) -> dict[str, Any]:
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


class ListPositionsArgs(_ToolArgs):
    limit: int = Field(25, ge=1, le=200)


@tool("list_positions", "Read current positions from the database.", ListPositionsArgs)
def _tool_list_positions(session: Session, _: str, args: ListPositionsArgs) -> dict[str, Any]:
    stmt = select(Position, Account).outerjoin(Account, Position.account_id == Account.id).order_by(func.abs(Position.position).desc()).limit(args.limit)
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


class ListJobsArgs(_ToolArgs):
    limit: int = Field(20, ge=1, le=200)
    include_archived: bool = False


@tool("list_jobs", "Read latest job queue records.", ListJobsArgs)
def _tool_list_jobs(session: Session, _: str, args: ListJobsArgs) -> dict[str, Any]:
    stmt = select(Job)
    if not args.include_archived:
        stmt = stmt.where(Job.archived_at.is_(None))
    rows = session.execute(stmt.order_by(Job.created_at.desc()).limit(args.limit)).scalars().all()
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


class ListOrdersArgs(_ToolArgs):
    limit: int = Field(20, ge=1, le=200)
    status: OptStr = None
    include_events: bool = True
    events_per_order: int = Field(3, ge=1, le=20)


@tool("list_orders", "Read latest order records and optional recent events.", ListOrdersArgs)
def _tool_list_orders(session: Session, _: str, args: ListOrdersArgs) -> dict[str, Any]:
    stmt = select(Order, Account).outerjoin(Account, Order.account_id == Account.id).order_by(Order.created_at.desc())
    if args.status is not None:
        stmt = stmt.where(func.lower(Order.status) == args.status.lower())
    rows = session.execute(stmt.limit(args.limit)).all()

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
            "order_type": order.order_type,
            "limit_price": order.limit_price,
            "tif": order.tif,
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
        if args.include_events:
            events = (
                session.execute(select(OrderEvent).where(OrderEvent.order_id == order.id).order_by(OrderEvent.created_at.desc()).limit(args.events_per_order))
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


class PreviewOrderArgs(_ToolArgs):
    account_id: int | None = None
    account: OptStr = Field(None, description="Account alias or account number when account_id is not provided.")
    symbol: str
    # The schema advertises the allowed values; normalize_order_create_input stays the one place that accepts or rejects a side.
    side: str = Field(json_schema_extra={"enum": ["BUY", "SELL", "buy", "sell"]})
    quantity: int = Field(ge=1)
    sec_type: str = "FUT"
    exchange: OptStr = None
    currency: str = "USD"
    order_type: str = "MKT"
    # Advertised as > 0 but not enforced here: a MKT order has always ignored its limit price, and LMT is checked in normalize_order_create_input.
    limit_price: float | None = Field(None, json_schema_extra={"exclusiveMinimum": 0})
    tif: str = "DAY"
    request_text: OptStr = None

    @field_validator("sec_type", "currency", "order_type", "tif")
    @classmethod
    def _blank_means_default(cls, value: str, info: ValidationInfo) -> str:
        return value.strip() or cls.model_fields[str(info.field_name)].default


def _resolve_order_tool_account(session: Session, args: PreviewOrderArgs) -> Account:
    if args.account_id is not None:
        account = session.get(Account, args.account_id)
        if account is None:
            raise ValueError(f"Account id {args.account_id} not found.")
        return account

    if args.account is None:
        raise ValueError("Provide 'account_id' or 'account' (alias/account number).")

    lowered = args.account.lower()
    stmt = select(Account).where(
        or_(
            func.lower(Account.alias) == lowered,
            func.lower(Account.account) == lowered,
        )
    )
    account = session.execute(stmt).scalars().first()
    if account is None:
        raise ValueError(f"Account '{args.account}' not found.")
    return account


def _build_order_input_from_tool_args(
    session: Session,
    args: PreviewOrderArgs,
    *,
    latest_user_text: str,
) -> tuple[Account, OrderCreateInput]:
    account = _resolve_order_tool_account(session, args)
    exchange = args.exchange or _resolve_exchange(args.symbol.strip().upper(), args.sec_type.strip().upper())

    normalized = normalize_order_create_input(
        OrderCreateInput(
            account_id=account.id,
            symbol=args.symbol,
            side=args.side,
            quantity=args.quantity,
            sec_type=args.sec_type,
            exchange=exchange,
            currency=args.currency,
            order_type=args.order_type,
            limit_price=args.limit_price,
            tif=args.tif,
            source=_TOOL_SOURCE,
            request_text=args.request_text or latest_user_text,
        )
    )
    return account, normalized


def _order_summary_payload(order_input: OrderCreateInput) -> dict[str, Any]:
    return {
        "account_id": order_input.account_id,
        "symbol": order_input.symbol,
        "side": order_input.side,
        "quantity": order_input.quantity,
        "sec_type": order_input.sec_type,
        "exchange": order_input.exchange,
        "currency": order_input.currency,
        "order_type": order_input.order_type,
        "limit_price": order_input.limit_price,
        "tif": order_input.tif,
        "source": order_input.source,
        "request_text": order_input.request_text,
    }


@tool("preview_order", "Validate and normalize an order request without writing to the database.", PreviewOrderArgs)
def _tool_preview_order(session: Session, latest_user_text: str, args: PreviewOrderArgs) -> dict[str, Any]:
    account, order_input = _build_order_input_from_tool_args(
        session,
        args,
        latest_user_text=latest_user_text,
    )
    return {
        "preview": _order_summary_payload(order_input),
        "account": {
            "id": account.id,
            "alias": account.alias,
            "masked_account": mask_ibkr_account(account.account),
        },
        "message": "Preview only. No order was queued.",
    }


class EnqueueJobArgs(_ToolArgs):
    request_text: OptStr = None
    max_attempts: int = Field(3, ge=1, le=10)


class EnqueueContractsSyncArgs(EnqueueJobArgs):
    symbol: OptStr = Field(None, description="Ticker symbol, e.g. CL, ES, NQ, AAPL")
    sec_type: OptStr = Field(None, description="Security type to sync", json_schema_extra={"enum": ["FUT", "OPT", "FOP", "STK"]})


def _no_payload(_: Any) -> dict[str, Any]:
    return {}


def _contracts_sync_payload(args: EnqueueContractsSyncArgs) -> dict[str, Any]:
    if args.symbol is None and args.sec_type is None:
        return {}
    sym = (args.symbol or "CL").upper()
    st = (args.sec_type or "FUT").upper()
    return {"specs": [{"symbol": sym, "sec_type": st, "exchange": _resolve_exchange(sym, st)}]}


def _enqueue_job_tool(
    name: str,
    description: str,
    job_type: str,
    args: type[EnqueueJobArgs] = EnqueueJobArgs,
    build_payload: Callable[[Any], dict[str, Any]] = _no_payload,
) -> None:
    """Register a tool that enqueues one ``job_type`` job for the worker and reports the queued job."""

    def run(session: Session, latest_user_text: str, tool_args: EnqueueJobArgs) -> dict[str, Any]:
        job = enqueue_job(
            session=session,
            job_type=job_type,
            payload=build_payload(tool_args),
            source=_TOOL_SOURCE,
            request_text=tool_args.request_text or latest_user_text,
            max_attempts=tool_args.max_attempts,
        )
        session.commit()
        return {
            "job_id": job.id,
            "job_type": job.job_type,
            "status": job.status,
            "max_attempts": job.max_attempts,
        }

    _register_tool(Tool(name=name, description=description, args=args, run=run))


_enqueue_job_tool(
    "enqueue_positions_sync_job",
    "Enqueue a positions.sync job for worker:jobs to process.",
    JOB_TYPE_POSITIONS_SYNC_FLEXQUERY,
)
_enqueue_job_tool(
    "enqueue_order_fetch_sync_job",
    "Enqueue an order.fetch_sync job for worker:jobs to pull broker orders into the database.",
    JOB_TYPE_ORDER_FETCH_SYNC,
)
_enqueue_job_tool(
    "enqueue_contracts_sync_job",
    (
        "Enqueue a contracts.sync job to fetch available contracts from IBKR into the database. "
        "Pass symbol and sec_type to sync a specific instrument (e.g. NQ FUT, AAPL STK). "
        "Defaults to CL FUT if not specified."
    ),
    JOB_TYPE_CONTRACTS_SYNC,
    args=EnqueueContractsSyncArgs,
    build_payload=_contracts_sync_payload,
)


class _ContractQueryArgs(_ToolArgs):
    """The contract-selecting arguments shared by lookup_contract and add_watch_list_instrument."""

    contract_expiry: OptStr = Field(
        None,
        description="Specific expiry date YYYY-MM-DD (e.g. '2026-03-16'). Use this for weekly options instead of contract_month.",
    )
    strike: float | None = Field(None, description="Strike price for OPT/FOP")
    # The schema advertises C/P; the handler upper-cases whatever it gets, as it always has.
    right: OptStr = Field(None, description="Call or Put for OPT/FOP", json_schema_extra={"enum": ["C", "P"]})


class LookupContractArgs(_ContractQueryArgs):
    symbol: NonBlankStr = Field(description="Ticker symbol, e.g. CL, ES, NQ, AAPL")
    sec_type: NonBlankStr = Field(json_schema_extra={"enum": ["FUT", "OPT", "FOP", "STK"]})
    contract_month: OptStr = Field(None, description="YYYY-MM or month name like 'March 2026'")


def _pending_lookup_result(session: Session, lookup: ContractLookup, **context: Any) -> dict[str, Any]:
    """Commit the contracts.sync job queued by a lookup miss and report it to the model."""
    session.commit()
    return {**context, "pending_job_id": lookup.pending_job_id, "message": lookup.message}


@tool(
    "lookup_contract",
    (
        "Look up contract details. Checks the database first; if no contracts are found, "
        "it queues a contracts.sync job to fetch them from IBKR and returns pending_job_id "
        "with no contracts. Tell the user to check back shortly, then repeat the lookup. "
        "Use this for informational queries like 'what is the front month for CL?' "
        "or 'what NQ contracts are available?'."
    ),
    LookupContractArgs,
)
def _tool_lookup_contract(session: Session, _: str, args: LookupContractArgs) -> dict[str, Any]:
    symbol = args.symbol.upper()
    sec_type = args.sec_type.upper()
    requested_contract_month = normalize_contract_month_input(args.contract_month)
    contract_expiry = args.contract_expiry
    strike = args.strike
    right = args.right.upper() if args.right is not None else None

    min_days_to_expiry = get_int_env("BROKER_CL_MIN_DAYS_TO_EXPIRY", DEFAULT_CL_MIN_DAYS_TO_EXPIRY)

    lookup = find_contracts_with_fallback(
        session=session,
        symbol=symbol,
        sec_type=sec_type,
        contract_month=requested_contract_month,
        min_days_to_expiry=min_days_to_expiry,
        strike=strike,
        right=right,
        contract_expiry=contract_expiry,
    )
    if lookup.pending_job_id is not None:
        return _pending_lookup_result(session, lookup, symbol=symbol, sec_type=sec_type, total_contracts=0)
    contracts = lookup.contracts

    # For FOP/OPT, include individual contracts so the agent can see available expiry dates
    if sec_type in ("FOP", "OPT"):
        # Group by expiry for a concise summary
        by_expiry: dict[str, list[dict[str, Any]]] = {}
        for c in contracts:
            expiry = c.get("contract_expiry") or "unknown"
            by_expiry.setdefault(expiry, []).append(c)

        expiry_summary = []
        for expiry, group in sorted(by_expiry.items()):
            expiry_summary.append(
                {
                    "contract_expiry": expiry,
                    "days_to_expiry": group[0]["days_to_expiry"],
                    "count": len(group),
                    "contracts": [
                        {
                            "con_id": c["con_id"],
                            "local_symbol": c["local_symbol"],
                            "strike": c["strike"],
                            "right": c["right"],
                            "contract_expiry": c["contract_expiry"],
                            "days_to_expiry": c["days_to_expiry"],
                        }
                        for c in group[:10]  # cap per expiry to avoid huge responses
                    ],
                }
            )

        return {
            "symbol": symbol,
            "sec_type": sec_type,
            "total_contracts": len(contracts),
            "available_expiries": expiry_summary,
        }

    # Group by month for FUT summary
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


@tool(
    "list_activated_products",
    (
        "List the futures products actively maintained in the security master "
        "(e.g. CL, NG, ZB, ZN, ES, NQ), with their discovered exchange, discovery "
        "status, and how many active contracts are in the database. Use this to see "
        "the tradable universe before looking up specific contract months."
    ),
    _NoArgs,
)
def _tool_list_activated_products(session: Session, _: str, args: _NoArgs) -> dict[str, Any]:
    from src.models import ActivatedProduct, ContractRef

    products = session.execute(select(ActivatedProduct).order_by(ActivatedProduct.symbol.asc())).scalars().all()

    count_rows = session.execute(
        select(ContractRef.symbol, ContractRef.sec_type, func.count(ContractRef.id))
        .where(ContractRef.is_active.is_(True))
        .group_by(ContractRef.symbol, ContractRef.sec_type)
    ).all()
    counts = {(symbol, sec_type): count for symbol, sec_type, count in count_rows}

    return {
        "products": [
            {
                "symbol": p.symbol,
                "sec_type": p.sec_type,
                "exchange": p.exchange,
                "discovery_status": p.discovery_status,
                "months_ahead": p.months_ahead,
                "security_master_count": counts.get((p.symbol, p.sec_type), 0),
                "last_synced_at": _iso(p.last_synced_at),
                "is_active": p.is_active,
            }
            for p in products
        ]
    }


@tool("list_watch_lists", "List all watch lists with instrument counts.", _NoArgs)
def _tool_list_watch_lists(session: Session, _: str, args: _NoArgs) -> dict[str, Any]:
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


class CreateWatchListArgs(_ToolArgs):
    name: NonBlankStr = Field(description="Name of the watch list")
    description: OptStr = Field(None, description="Optional description")


@tool("create_watch_list", "Create a new watch list.", CreateWatchListArgs)
def _tool_create_watch_list(session: Session, _: str, args: CreateWatchListArgs) -> dict[str, Any]:
    wl = WatchList(name=args.name, description=args.description)
    session.add(wl)
    session.commit()
    session.refresh(wl)
    return {"id": wl.id, "name": wl.name, "description": wl.description}


class GetWatchListArgs(_ToolArgs):
    watch_list_id: int = Field(description="ID of the watch list")


@tool("get_watch_list", "Get a watch list with all its instruments.", GetWatchListArgs)
def _tool_get_watch_list(session: Session, _: str, args: GetWatchListArgs) -> dict[str, Any]:
    from src.models import ContractRef

    wl_id = args.watch_list_id
    wl = session.get(WatchList, wl_id)
    if wl is None:
        raise ValueError(f"Watch list #{wl_id} not found.")
    rows = session.execute(
        select(WatchListInstrument, ContractRef)
        .join(ContractRef, ContractRef.con_id == WatchListInstrument.con_id)
        .where(WatchListInstrument.watch_list_id == wl_id)
        .order_by(WatchListInstrument.created_at)
    ).all()
    return {
        "id": wl.id,
        "name": wl.name,
        "description": wl.description,
        "instruments": [
            {
                "id": inst.id,
                "con_id": inst.con_id,
                "symbol": contract.symbol,
                "sec_type": contract.sec_type,
                "exchange": contract.exchange,
                "local_symbol": contract.local_symbol,
                "contract_month": contract.contract_month,
                "contract_expiry": contract.contract_expiry,
                "strike": contract.strike,
                "right": contract.right,
            }
            for inst, contract in rows
        ],
    }


class AddWatchListInstrumentArgs(_ContractQueryArgs):
    watch_list_id: int = Field(description="ID of the watch list to add to")
    symbol: NonBlankStr = Field(description="Ticker symbol, e.g. CL, ES, AAPL")
    sec_type: NonBlankStr = Field(description="Security type", json_schema_extra={"enum": ["STK", "FUT", "OPT", "FOP"]})
    contract_month: OptStr = Field(None, description="YYYY-MM or month name like 'April 2026'")


@tool(
    "add_watch_list_instrument",
    (
        "Add an instrument to a watch list. Looks up the contract in the DB first. If it is not there yet, "
        "it queues a contracts.sync job to fetch it from IBKR and returns pending_job_id without adding "
        "anything: tell the user to check back shortly, then repeat the request. If it is found, adds it "
        "to the watch list and enqueues a market data job to fetch latest prices. Returns immediately with the result."
    ),
    AddWatchListInstrumentArgs,
)
def _tool_add_watch_list_instrument(session: Session, latest_user_text: str, args: AddWatchListInstrumentArgs) -> dict[str, Any]:
    wl_id = args.watch_list_id
    wl = session.get(WatchList, wl_id)
    if wl is None:
        raise ValueError(f"Watch list #{wl_id} not found.")

    symbol = args.symbol.upper()
    sec_type = args.sec_type.upper()
    if sec_type not in {"STK", "FUT", "OPT", "FOP"}:
        raise ValueError("'sec_type' must be one of STK, FUT, OPT, FOP.")

    requested_contract_month = normalize_contract_month_input(args.contract_month)
    contract_expiry = args.contract_expiry
    strike = args.strike
    right = args.right.upper() if args.right is not None else None

    # 1. Find contract in DB; on a miss a contracts.sync job is queued and nothing is added yet
    lookup = find_contracts_with_fallback(
        session=session,
        symbol=symbol,
        sec_type=sec_type,
        contract_month=requested_contract_month,
        strike=strike,
        right=right,
        contract_expiry=contract_expiry,
    )
    if lookup.pending_job_id is not None:
        return _pending_lookup_result(session, lookup, watch_list_id=wl_id, symbol=symbol, sec_type=sec_type)

    # Pick the first (front) contract
    contract = lookup.contracts[0]
    con_id = contract["con_id"]

    # 2. Check for duplicate in watch list
    from sqlalchemy import select as sa_select

    existing = (
        session.execute(
            sa_select(WatchListInstrument).where(
                WatchListInstrument.watch_list_id == wl_id,
                WatchListInstrument.con_id == con_id,
            )
        )
        .scalars()
        .first()
    )

    if existing is not None:
        instrument_id = existing.id
        already_existed = True
    else:
        inst = WatchListInstrument(
            watch_list_id=wl_id,
            con_id=con_id,
        )
        session.add(inst)
        session.flush()
        instrument_id = inst.id
        already_existed = False

    # 3. Enqueue a market data snapshot for this specific contract
    md_job = enqueue_job(
        session=session,
        job_type=JOB_TYPE_MARKET_DATA_SNAPSHOT,
        payload={"con_ids": [con_id]},
        source=_TOOL_SOURCE,
        request_text=f"fetch prices for {symbol} {sec_type} con_id={con_id}",
    )

    session.commit()

    result: dict[str, Any] = {
        "con_id": con_id,
        "local_symbol": contract.get("local_symbol"),
        "contract_expiry": contract.get("contract_expiry"),
        "strike": contract.get("strike"),
        "right": contract.get("right"),
        "watch_list_id": wl_id,
        "instrument_id": instrument_id,
        "already_existed": already_existed,
        "message": f"{'Already in' if already_existed else 'Added to'} watch list #{wl_id}: {contract.get('local_symbol') or symbol}",
    }
    result["price_fetch_job_id"] = md_job.id
    result["message"] += f". Enqueued price fetch job #{md_job.id}."
    return result


class RemoveWatchListInstrumentArgs(_ToolArgs):
    watch_list_id: int = Field(description="ID of the watch list")
    instrument_id: int = Field(description="ID of the instrument to remove")


@tool("remove_watch_list_instrument", "Remove an instrument from a watch list.", RemoveWatchListInstrumentArgs)
def _tool_remove_watch_list_instrument(session: Session, _: str, args: RemoveWatchListInstrumentArgs) -> dict[str, Any]:
    wl_id = args.watch_list_id
    inst_id = args.instrument_id

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


class CheckWatchlistJobArgs(_ToolArgs):
    job_id: int = Field(description="The job ID returned by add_watch_list_instrument")


@tool(
    "check_watchlist_job",
    (
        "Poll a watchlist.add_instrument job for its result. "
        "Returns instrument details when completed, error when failed, "
        "or a 'still running' message if not yet done. Call again if still running."
    ),
    CheckWatchlistJobArgs,
)
def _tool_check_watchlist_job(session: Session, _: str, args: CheckWatchlistJobArgs) -> dict[str, Any]:
    job_id = args.job_id

    job = session.get(Job, job_id)
    if job is None:
        raise ValueError(f"Job #{job_id} not found.")
    if job.job_type != JOB_TYPE_WATCHLIST_ADD_INSTRUMENT:
        raise ValueError(f"Job #{job_id} is not a watchlist.add_instrument job (it is '{job.job_type}').")

    if job.status == JobStatus.COMPLETED:
        return {
            "status": JobStatus.COMPLETED,
            "result": job.result,
        }
    elif job.status == JobStatus.FAILED:
        return {
            "status": JobStatus.FAILED,
            "error": job.last_error,
        }
    else:
        return {
            "status": job.status,
            "message": "Job is still running. Call check_watchlist_job again shortly.",
        }


class TradeGroupPnlArgs(_ToolArgs):
    group: Annotated[str | int, AfterValidator(_group_not_blank)] = Field(description="Trade group name or numeric id.")


@tool(
    "trade_group_pnl",
    (
        "Realized + unrealized PnL for ONE trade group, matching the trade group detail view. "
        "Returns realized_pnl (settled), settled_unrealized_pnl, and the live-overlay figures "
        "intraday_unrealized_pnl / intraday_realized_pnl / intraday_total_pnl plus marks_as_of. "
        "Intraday figures are 'as of the last live TWS refresh', not tick-live, and are a per-group "
        "attribution (not additive across groups). For analytics across many groups use query_metric "
        "(e.g. realized_pnl grouped by trade_group)."
    ),
    TradeGroupPnlArgs,
)
def _tool_trade_group_pnl(session: Session, _: str, args: TradeGroupPnlArgs) -> dict[str, Any]:
    group = resolve_trade_group(session, args.group)
    return compute_trade_group_pnl(session, group.id).as_dict()


class QueryMetricArgs(_ToolArgs):
    """Validation only; the published schema is built from the semantic model (see ``_register_query_metric_tool``)."""

    metric: Annotated[str, AfterValidator(_require_non_blank)]
    group_by: list[str] | None = None
    filters: dict[str, Any] | None = None
    start_date: OptStr = None
    end_date: OptStr = None
    time_grain: OptStr = None
    limit: int = Field(50, ge=1, le=500)


def _tool_query_metric(session: Session, _: str, args: QueryMetricArgs) -> dict[str, Any]:
    model = get_model()
    query = build_metric_query(
        model,
        metric=args.metric,
        group_by=args.group_by or [],
        equality_filters=args.filters or {},
        date_start=args.start_date,
        date_end=args.end_date,
        time_grain=args.time_grain,
        limit=args.limit,
    )
    rows = run_metric_query(session.get_bind(), query)
    return {
        "metric": query.metric,
        "group_by": list(query.group_by),
        "row_count": len(rows),
        "rows": rows,
        "sql": query.sql,
    }


def _register_query_metric_tool() -> None:
    """Register query_metric, or skip it entirely if the semantic model cannot load.

    The spec and the handler enter ``TOOLS`` together here, so a model failure removes the tool from
    both ``_TOOL_SPECS`` and ``_TOOL_HANDLERS`` and the agent never advertises a tool it cannot run.
    """
    try:
        description, parameters = _build_query_metric_schema()
    except Exception as exc:  # noqa: BLE001 — a bad model file must not break the whole agent
        logger.error("query_metric tool disabled: failed to load semantic model: %s", exc)
        return
    _register_tool(Tool(name="query_metric", description=description, args=QueryMetricArgs, run=_tool_query_metric, parameters=parameters))


_register_query_metric_tool()

_TOOL_SPECS: list[dict[str, Any]] = [registered.spec() for registered in TOOLS]
# Name -> Tool; ``_execute_tool_call`` validates through ``Tool.args`` and then calls ``Tool.run``.
_TOOL_HANDLERS: dict[str, Tool] = {registered.name: registered for registered in TOOLS}


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


class _ToolArgsError(ValueError):
    """The model's arguments for a tool could not be parsed or failed validation."""


def _parse_tool_args(tool_to_run: Tool, arguments_json: str) -> BaseModel:
    try:
        args_obj = json.loads(arguments_json) if arguments_json.strip() else {}
    except json.JSONDecodeError as exc:
        raise _ToolArgsError(f"Arguments for tool '{tool_to_run.name}' were not valid JSON.") from exc

    if not isinstance(args_obj, dict):
        raise _ToolArgsError(f"Arguments for tool '{tool_to_run.name}' must be an object.")

    try:
        return tool_to_run.args.model_validate(args_obj)
    except ValidationError as exc:
        raise _ToolArgsError(_format_validation_error(tool_to_run.name, exc)) from exc


def _execute_tool_call(
    session: Session,
    latest_user_text: str,
    tool_name: str,
    arguments_json: str,
) -> dict[str, Any]:
    tool_to_run = _TOOL_HANDLERS.get(tool_name)
    if tool_to_run is None:
        return {"ok": False, "error": f"Unknown tool '{tool_name}'."}

    try:
        args = _parse_tool_args(tool_to_run, arguments_json)
    except _ToolArgsError as exc:
        return {"ok": False, "error": str(exc)}

    try:
        return {"ok": True, "result": tool_to_run.run(session, latest_user_text, args)}
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
        final_text = assistant_text.strip() or ("I could not complete that request with confidence. Please retry with a more specific instruction.")
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
            "final_text": ("I could not complete that request with confidence. Please retry with a more specific instruction."),
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
        "final_text": ("I reached the maximum number of tool steps for this request. Please retry with a more specific instruction."),
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

    return "I could not complete that request with confidence. Please retry with a more specific instruction."
