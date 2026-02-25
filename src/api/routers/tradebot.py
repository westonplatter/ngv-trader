"""Tradebot chat router backed by the LangGraph tradebot agent."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.deps import get_db
from src.services.tradebot_agent import ChatInputMessage, run_tradebot_agent

router = APIRouter()
DB_SESSION_DEPENDENCY = Depends(get_db)


class ChatPart(BaseModel):
    type: str
    text: str | None = None


class ChatMessage(BaseModel):
    role: str
    parts: list[ChatPart]


class TradebotChatRequest(BaseModel):
    messages: list[ChatMessage]


def _extract_message_text(message: ChatMessage) -> str:
    parts = [part.text.strip() for part in message.parts if part.type == "text" and part.text and part.text.strip()]
    return "\n".join(parts)


def _to_agent_messages(messages: list[ChatMessage]) -> list[ChatInputMessage]:
    normalized: list[ChatInputMessage] = []
    for message in messages:
        text = _extract_message_text(message)
        if not text:
            continue
        normalized.append(
            ChatInputMessage(
                role=message.role,
                text=text,
            )
        )
    return normalized


@router.post("/tradebot/chat", response_class=PlainTextResponse)
def tradebot_chat(body: TradebotChatRequest, db: Session = DB_SESSION_DEPENDENCY) -> str:
    normalized_messages = _to_agent_messages(body.messages)
    if not normalized_messages:
        raise HTTPException(status_code=400, detail="No chat message text found")

    try:
        return run_tradebot_agent(db, normalized_messages)
    except ValueError as exc:
        return f"Tradebot request/config error: {exc}"
    except Exception as exc:  # noqa: BLE001
        return f"Tradebot error: {exc}"
