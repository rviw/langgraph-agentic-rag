import json

from pydantic import BaseModel

# Comment frame that keeps idle proxies from closing a slow answer's stream.
HEARTBEAT_FRAME = ": heartbeat\n\n"
HEARTBEAT_SECONDS = 10.0

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def event_frame(event: BaseModel) -> str:
    """Render one server-sent event named after the event's own type field."""

    payload = event.model_dump(mode="json")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {payload['type']}\ndata: {data}\n\n"
