"""HTTP routes: validate input, walk the chat flow, map errors to status codes."""

import secrets
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Header

from app.api.errors import ApiError
from app.api.schemas import (
    ChatHistoryResponse,
    ChatRequest,
    ChatResponse,
    ContactRequest,
    ContactResponse,
    Fallback,
    MessageOut,
)
from app.config import Settings, get_settings
from app.core.ai_service import (
    AIRateLimitError,
    AIService,
    AIUnavailableError,
    get_ai_service,
)
from app.core.prompt_builder import build_system_prompt
from app.data.repository import KnowledgeSource, get_booking_link, get_knowledge_source
from app.sessions.manager import SessionManager, get_session_manager
from app.sessions.models import Session

HISTORY_LIMIT = 10  # only the last N messages of a session go to the model

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def require_access_code(
    settings: Annotated[Settings, Depends(get_settings)],
    x_access_code: Annotated[str | None, Header()] = None,
) -> None:
    if x_access_code is None or not secrets.compare_digest(
        x_access_code.encode(), settings.access_code.encode()
    ):
        raise ApiError(401, "ACCESS_DENIED", "Missing or invalid access code.")


api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_access_code)])

AIServiceDep = Annotated[AIService, Depends(get_ai_service)]
KnowledgeDep = Annotated[KnowledgeSource, Depends(get_knowledge_source)]
SessionsDep = Annotated[SessionManager, Depends(get_session_manager)]


def _get_session_or_404(sessions: SessionManager, chat_id: str) -> Session:
    session = sessions.get_session(chat_id)
    if session is None:
        raise ApiError(404, "UNKNOWN_CHAT", "Unknown or expired chat.")
    return session


def _run_chat_turn(
    session: Session,
    message: str,
    ai: AIService,
    knowledge: KnowledgeSource,
    sessions: SessionManager,
) -> ChatResponse:
    sections = knowledge.retrieve(message)
    system_prompt = build_system_prompt(sections)
    history = [
        {"role": m.role, "content": m.content}
        for m in session.messages[-(HISTORY_LIMIT - 1):]
    ]
    history.append({"role": "user", "content": message})
    try:
        result = ai.get_response(
            [{"role": "system", "content": system_prompt}, *history], sections
        )
    except AIRateLimitError as exc:
        raise ApiError(
            429, "RATE_LIMITED", "The assistant is busy right now; try again shortly."
        ) from exc
    except AIUnavailableError as exc:
        raise ApiError(
            502, "AI_UNAVAILABLE", "The assistant is unavailable right now; try again shortly."
        ) from exc

    # Saved only after the model answered: a failed call must leave the
    # session exactly as it was, or a retry would duplicate the user turn.
    sessions.add_message(session, "user", message)
    sessions.add_message(
        session, "assistant", result.reply, fallback_reason=result.fallback_reason
    )
    structlog.get_logger().info(
        "chat_turn",
        chat_id=session.id,
        messages=len(session.messages),
        fallback=result.fallback_reason is not None,
    )
    fallback = (
        None
        if result.fallback_reason is None
        else Fallback(reason=result.fallback_reason, booking_url=get_booking_link())
    )
    return ChatResponse(chat_id=session.id, reply=result.reply, fallback=fallback)


@api_router.post("/chat")
def start_chat(
    request: ChatRequest,
    ai: AIServiceDep,
    knowledge: KnowledgeDep,
    sessions: SessionsDep,
) -> ChatResponse:
    session = sessions.create_session()
    return _run_chat_turn(session, request.message, ai, knowledge, sessions)


@api_router.post("/chat/{chat_id}/messages")
def continue_chat(
    chat_id: str,
    request: ChatRequest,
    ai: AIServiceDep,
    knowledge: KnowledgeDep,
    sessions: SessionsDep,
) -> ChatResponse:
    session = _get_session_or_404(sessions, chat_id)
    return _run_chat_turn(session, request.message, ai, knowledge, sessions)


@api_router.get("/chat/{chat_id}")
def get_chat(chat_id: str, sessions: SessionsDep) -> ChatHistoryResponse:
    session = _get_session_or_404(sessions, chat_id)
    return ChatHistoryResponse(
        chat_id=session.id,
        messages=[
            MessageOut(
                role=m.role,
                content=m.content,
                fallback=(
                    None
                    if m.fallback_reason is None
                    else Fallback(
                        reason=m.fallback_reason, booking_url=get_booking_link()
                    )
                ),
            )
            for m in session.messages
        ],
    )


@api_router.post("/chat/{chat_id}/contact")
def leave_contact(
    chat_id: str, request: ContactRequest, sessions: SessionsDep
) -> ContactResponse:
    session = _get_session_or_404(sessions, chat_id)
    sessions.set_contact(session, request.name, request.email)
    structlog.get_logger().info(
        "contact_captured", chat_id=session.id, name=request.name, email=request.email
    )
    return ContactResponse()
