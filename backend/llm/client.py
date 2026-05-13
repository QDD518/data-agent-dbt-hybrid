"""LLM client wrapper — unified interface for OpenAI / compatible APIs."""

from openai import OpenAI

from backend.config import settings


_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _client


def chat(messages: list[dict], model: str | None = None, temperature: float = 0.1) -> str:
    """Simple chat completion. Returns the assistant's text response."""
    client = get_client()
    response = client.chat.completions.create(
        model=model or settings.llm_model,
        messages=messages,
        temperature=temperature,
    )
    return response.choices[0].message.content or ""


def get_embeddings(texts: list[str], model: str | None = None) -> list[list[float]]:
    """Get embeddings for a list of texts."""
    client = get_client()
    response = client.embeddings.create(
        model=model or settings.llm_embedding_model,
        input=texts,
    )
    return [d.embedding for d in response.data]
