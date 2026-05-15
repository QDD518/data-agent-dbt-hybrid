"""SSE client — streams events from the Chat BI backend."""

import json
from typing import Generator

import httpx

BACKEND_URL = "http://localhost:8000"


def stream_chat(message: str) -> Generator[dict, None, None]:
    """POST to /api/chat and yield SSE events as they arrive."""
    with httpx.Client(timeout=90, trust_env=False) as client:
        with client.stream(
            "POST",
            f"{BACKEND_URL}/api/chat",
            json={"message": message, "conversation_id": None},
        ) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line.startswith("data: "):
                    data_str = line[len("data: "):]
                    try:
                        yield json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
