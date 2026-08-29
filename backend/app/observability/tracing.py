"""Trace chat executions in Langfuse without exporting credentials."""

import asyncio
import logging
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from uuid import UUID

from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from langfuse.types import MaskOtelSpansParams, MaskOtelSpansResult, OtelSpanPatch

from app.observability.privacy import SecretRedactor

if TYPE_CHECKING:
    from app.core.config import Settings

logger = logging.getLogger(__name__)

EXPORT_TIMEOUT_SECONDS = 30
# Media extraction runs before masking, so it stays off to keep PDF bytes local.
MEDIA_UPLOAD_ENV = "LANGFUSE_MEDIA_UPLOAD_ENABLED"
# Tracing is a side channel, so a process can run with it switched off.
TRACING_ENABLED_ENV = "LANGFUSE_TRACING_ENABLED"

_CALLBACKS: ContextVar[tuple[Any, ...]] = ContextVar("trace_callbacks", default=())


def build_span_mask(
    redactor: SecretRedactor,
) -> Callable[..., MaskOtelSpansResult | None]:
    """Redact span attributes at export, after every instrumentation has run."""

    def mask_otel_spans(*, params: MaskOtelSpansParams) -> MaskOtelSpansResult | None:
        patches: dict[Any, OtelSpanPatch] = {}
        for identifier, span in params.spans.items():
            replacements = {
                key: redactor.redact(value, key=key)
                for key, value in span.attributes.items()
                if redactor.redact(value, key=key) != value
            }
            if replacements:
                patches[identifier] = OtelSpanPatch(set_attributes=replacements)
        return MaskOtelSpansResult(span_patches=patches) if patches else None

    return mask_otel_spans


class ChatExecutionTracer:
    """Record one chat execution as a trace, redacting everything it exports."""

    def __init__(
        self, *, client: Any, public_key: str, redactor: SecretRedactor
    ) -> None:
        self._client = client
        self._public_key = public_key
        self._redactor = redactor

    @contextmanager
    def trace_execution(
        self,
        *,
        execution_id: UUID,
        chat_id: UUID,
        user_id: UUID,
    ) -> Iterator[None]:
        manager = self._client.start_as_current_observation(
            as_type="agent",
            name="chat-execution",
            metadata=self._redactor.redact(
                {
                    "app.execution.id": str(execution_id),
                    "app.chat.id": str(chat_id),
                    "app.user.id": str(user_id),
                }
            ),
        )
        try:
            manager.__enter__()
        except Exception:
            logger.warning("Langfuse trace could not be started")
            yield
            return

        callback = CallbackHandler(public_key=self._public_key)
        token = _CALLBACKS.set((callback,))
        try:
            yield
        finally:
            _CALLBACKS.reset(token)
            try:
                manager.__exit__(None, None, None)
            except Exception:
                logger.warning("Langfuse trace could not be finished")

    async def shutdown(self) -> None:
        try:
            await asyncio.to_thread(self._client.shutdown)
        except Exception:
            logger.warning("Langfuse shutdown failed")


class DisabledTracer:
    """Runs chats without exporting traces, for tests and offline runs."""

    @contextmanager
    def trace_execution(
        self,
        *,
        execution_id: UUID,
        chat_id: UUID,
        user_id: UUID,
    ) -> Iterator[None]:
        del execution_id, chat_id, user_id
        yield

    async def shutdown(self) -> None:
        pass


def build_chat_execution_tracer(
    settings: Settings,
) -> ChatExecutionTracer | DisabledTracer:
    # The exporter starts background workers as soon as it is created, so a
    # process that should not export never builds one.
    if os.environ.get(TRACING_ENABLED_ENV, "true").lower() == "false":
        return DisabledTracer()

    public_key = settings.LANGFUSE_PUBLIC_KEY.get_secret_value()
    secret_key = settings.LANGFUSE_SECRET_KEY.get_secret_value()
    redactor = SecretRedactor(
        (
            public_key,
            secret_key,
            str(settings.DATABASE_URL),
            settings.SUPABASE_PUBLISHABLE_KEY.get_secret_value(),
            settings.SUPABASE_SECRET_KEY.get_secret_value(),
            settings.OPENAI_API_KEY.get_secret_value(),
            settings.COHERE_API_KEY.get_secret_value(),
            settings.TAVILY_API_KEY.get_secret_value(),
        )
    )

    os.environ[MEDIA_UPLOAD_ENV] = "false"
    client = Langfuse(
        public_key=public_key,
        secret_key=secret_key,
        base_url=str(settings.LANGFUSE_BASE_URL),
        timeout=EXPORT_TIMEOUT_SECONDS,
        # Two layers: the SDK mask for payloads, the span mask for attributes.
        mask=lambda *, data, **_kwargs: redactor.redact(data),
        mask_otel_spans=build_span_mask(redactor),
    )
    return ChatExecutionTracer(
        client=client,
        public_key=public_key,
        redactor=redactor,
    )


def current_trace_callbacks() -> list[Any]:
    """Callbacks that attach model and tool calls to the active execution trace."""

    return list(_CALLBACKS.get())


def traced_config(
    *,
    run_name: str,
    metadata: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    config: dict[str, Any] = {
        "callbacks": current_trace_callbacks(),
        "run_name": run_name,
    }
    if metadata is not None:
        config["metadata"] = dict(metadata)
    return config
