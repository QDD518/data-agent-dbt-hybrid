"""Chat orchestration through validated QueryPlan and deterministic SQL compiler."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from backend.agent.planner import resolve_query_plan
from backend.agent.router import classify_intent
from backend.llm.client import chat
from backend.rag.retriever import retrieve_context
from backend.semantic.compiler import QueryCompilationError, compile_query
from backend.semantic.query_plan import MetadataQueryPlan, PlanValidationError
from backend.semantic.query_builder import MetricQueryBuilder  # legacy patch point for downstream clients
from backend.semantic.registry import SemanticRegistryError, load_registry
from backend.sql.executor import execute_sql
from backend.sql.security import SQLSecurityError


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


async def process_message(message: str) -> AsyncGenerator[str, None]:
    """Classify, plan, validate, compile, execute and interpret one question."""
    yield _sse("status", {"stage": "classifying", "message": "Analyzing your question..."})
    loop = asyncio.get_running_loop()
    intent = await loop.run_in_executor(None, classify_intent, message)
    path = intent.get("path", "exploratory")
    yield _sse("status", {"stage": "classified", "path": path, "intent": intent})

    try:
        registry = await loop.run_in_executor(None, load_registry)
        plan = await loop.run_in_executor(
            None, lambda: resolve_query_plan(message, intent, registry)
        )
    except (PlanValidationError, SemanticRegistryError) as exc:
        yield _sse("error", {"message": str(exc)})
        return
    except Exception as exc:
        yield _sse("error", {"message": f"Unable to create a query plan: {exc}"})
        return

    yield _sse("plan", {"plan": plan.model_dump()})
    if isinstance(plan, MetadataQueryPlan):
        async for event in _handle_metadata(message):
            yield event
        return

    yield _sse("status", {"stage": "building_sql", "message": "Compiling validated query plan..."})
    try:
        compiled = await loop.run_in_executor(None, lambda: compile_query(plan, registry))
    except (QueryCompilationError, PlanValidationError, SemanticRegistryError) as exc:
        yield _sse("error", {"message": str(exc)})
        return

    yield _sse("sql", {"sql": compiled.sql})
    yield _sse("status", {"stage": "executing", "message": "Running query..."})
    try:
        result = await loop.run_in_executor(None, execute_sql, compiled.sql)
    except SQLSecurityError as exc:
        yield _sse("error", {"message": f"SQL rejected: {exc}"})
        return
    except Exception as exc:
        yield _sse("error", {"message": f"Query failed: {exc}"})
        return

    yield _sse("result", {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    })
    yield _sse("status", {"stage": "interpreting", "message": "Generating summary..."})
    yield _sse("done", {"summary": await _interpret_results(message, result)})


async def _handle_metadata(message: str) -> AsyncGenerator[str, None]:
    yield _sse("status", {"stage": "retrieving_docs", "message": "Searching documentation..."})
    loop = asyncio.get_running_loop()
    context_docs = await loop.run_in_executor(None, retrieve_context, message, 5)
    context = "\n".join(f"- {document}" for document in context_docs)
    yield _sse("status", {"stage": "answering", "message": "Generating answer..."})
    response = await loop.run_in_executor(
        None,
        chat,
        [
            {
                "role": "system",
                "content": (
                    "You are a data documentation assistant. Answer only from the supplied "
                    "dbt and ontology metadata. If it is absent, say so.\n\n"
                    f"## Context:\n{context}"
                ),
            },
            {"role": "user", "content": message},
        ],
    )
    yield _sse("done", {"answer": response, "sources": context_docs[:3]})


_INTERPRET_PROMPT = """You are a data analyst. Summarize the query results for the user.

User question: {question}

Query results:
Columns: {columns}
Rows ({row_count} rows{truncated}):
{rows_preview}

Provide JSON only:
{{"summary": "2-4 sentence summary", "chart_type": "bar|line|pie|table", "insight": "one sentence"}}
"""


async def _interpret_results(message: str, result) -> dict:
    if result.row_count == 0:
        return {"summary": "Query returned no results.", "chart_type": "table", "insight": ""}
    rows_preview = "\n".join(str(row) for row in result.rows[:10])
    prompt = _INTERPRET_PROMPT.format(
        question=message or "data query",
        columns=", ".join(result.columns),
        row_count=result.row_count,
        truncated=", truncated" if result.truncated else "",
        rows_preview=rows_preview,
    )
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        chat,
        [{"role": "system", "content": prompt}, {"role": "user", "content": "Generate the JSON summary."}],
    )
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"summary": text, "chart_type": "table", "insight": ""}
