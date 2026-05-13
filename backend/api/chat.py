from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.agent.orchestrator import process_message

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., description="User question in natural language")
    conversation_id: str | None = Field(None, description="For multi-turn conversations")


@router.post("/api/chat")
async def chat(request: ChatRequest):
    """Main Chat API — SSE streaming through Path A/B/C pipeline."""
    return StreamingResponse(
        process_message(request.message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
