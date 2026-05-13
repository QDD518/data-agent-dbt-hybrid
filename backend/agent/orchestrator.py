"""Chat Orchestrator — routes user questions through Path A/B/C, streams SSE events."""

import asyncio
import json
from typing import AsyncGenerator

from backend.agent.router import classify_intent
from backend.semantic.query_builder import MetricQueryBuilder, SemanticQuery
from backend.sql.generator import generate_sql
from backend.sql.executor import execute_sql
from backend.sql.security import SQLSecurityError
from backend.rag.retriever import retrieve_context
from backend.llm.client import chat


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({'type': event_type, **data}, ensure_ascii=False)}\n\n"


async def process_message(message: str) -> AsyncGenerator[str, None]:
    """Main pipeline: route → execute → interpret. Yields SSE events."""

    # ── Phase 1: Intent Classification ──
    yield _sse("status", {"stage": "classifying", "message": "Analyzing your question..."})

    loop = asyncio.get_event_loop()
    intent = await loop.run_in_executor(None, classify_intent, message)
    path = intent.get("path", "exploratory")
    yield _sse("status", {"stage": "classified", "path": path, "intent": intent})

    # ── Phase 2: Execute by path ──
    if path == "metric_query":
        async for event in _handle_path_a(intent):
            yield event

    elif path == "exploratory":
        async for event in _handle_path_b(message):
            yield event

    elif path == "metadata":
        async for event in _handle_path_c(message):
            yield event

    else:
        yield _sse("error", {"message": f"Unknown path: {path}"})


async def _handle_path_a(intent: dict) -> AsyncGenerator[str, None]:
    """Path A: MetricFlow-style deterministic SQL from semantic metadata."""
    yield _sse("status", {"stage": "building_sql", "message": "Building metric query..."})

    loop = asyncio.get_event_loop()

    query = SemanticQuery(
        metric_names=intent.get("metric_names", []),
        dimensions=intent.get("dimensions", []),
        time_range=intent.get("time_range"),
    )

    if not query.metric_names:
        yield _sse("error", {"message": "No metrics identified. Please rephrase."})
        return

    try:
        builder = MetricQueryBuilder()
        sql = await loop.run_in_executor(None, builder.build_sql, query)
    except ValueError as e:
        yield _sse("error", {"message": str(e)})
        return

    yield _sse("sql", {"sql": sql})

    # Execute
    yield _sse("status", {"stage": "executing", "message": "Running query..."})
    try:
        result = await loop.run_in_executor(None, execute_sql, sql)
    except SQLSecurityError as e:
        yield _sse("error", {"message": f"SQL rejected: {e}"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Query failed: {e}"})
        return

    yield _sse("result", {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    })

    # Interpret
    yield _sse("status", {"stage": "interpreting", "message": "Generating summary..."})
    interpretation = await _interpret_results(message="", result=result)
    yield _sse("done", {"summary": interpretation})


async def _handle_path_b(message: str) -> AsyncGenerator[str, None]:
    """Path B: LLM Text-to-SQL for exploratory queries."""
    yield _sse("status", {"stage": "retrieving_context", "message": "Searching relevant data models..."})

    loop = asyncio.get_event_loop()

    # Retrieve relevant context
    context_docs = await loop.run_in_executor(None, retrieve_context, message, 5)
    yield _sse("context", {"documents": context_docs[:3]})

    # Generate SQL
    yield _sse("status", {"stage": "generating_sql", "message": "Generating SQL with LLM..."})
    sql = await loop.run_in_executor(None, generate_sql, message)

    if sql == "UNABLE_TO_GENERATE" or not sql:
        yield _sse("error", {"message": "Unable to generate SQL for this question. Try rephrasing."})
        return

    yield _sse("sql", {"sql": sql})

    # Execute
    yield _sse("status", {"stage": "executing", "message": "Running query..."})
    try:
        result = await loop.run_in_executor(None, execute_sql, sql)
    except SQLSecurityError as e:
        yield _sse("error", {"message": f"SQL rejected by security: {e}"})
        return
    except Exception as e:
        yield _sse("error", {"message": f"Query failed: {e}"})
        return

    yield _sse("result", {
        "columns": result.columns,
        "rows": result.rows,
        "row_count": result.row_count,
        "elapsed_ms": result.elapsed_ms,
        "truncated": result.truncated,
    })

    # Interpret
    yield _sse("status", {"stage": "interpreting", "message": "Generating summary..."})
    interpretation = await _interpret_results(message=message, result=result)
    yield _sse("done", {"summary": interpretation})


async def _handle_path_c(message: str) -> AsyncGenerator[str, None]:
    """Path C: RAG-based metadata Q&A — direct answer, no SQL."""
    yield _sse("status", {"stage": "retrieving_docs", "message": "Searching documentation..."})

    loop = asyncio.get_event_loop()
    context_docs = await loop.run_in_executor(None, retrieve_context, message, 5)
    context = "\n".join(f"- {doc}" for doc in context_docs)

    yield _sse("status", {"stage": "answering", "message": "Generating answer..."})

    response = await loop.run_in_executor(
        None,
        chat,
        [
            {
                "role": "system",
                "content": (
                    "You are a data documentation assistant. Answer the user's question "
                    "based on the following dbt metadata context. Be concise and accurate. "
                    "If the context doesn't contain the answer, say so.\n\n"
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

Provide:
1. A concise natural language summary (2-4 sentences)
2. A recommended chart type: one of "bar", "line", "pie", "table"
3. Key insight (1 sentence)

Output as JSON:
{{"summary": "...", "chart_type": "bar", "insight": "..."}}
"""


async def _interpret_results(message: str, result) -> dict:
    """Generate NL summary + chart recommendation from query results."""
    if result.row_count == 0:
        return {"summary": "查询未返回任何结果。", "chart_type": "table", "insight": ""}

    loop = asyncio.get_event_loop()

    # Preview first 10 rows max
    rows_preview = "\n".join(
        str(row) for row in result.rows[:10]
    )

    prompt = _INTERPRET_PROMPT.format(
        question=message or "data query",
        columns=", ".join(result.columns),
        row_count=result.row_count,
        truncated=", truncated" if result.truncated else "",
        rows_preview=rows_preview,
    )

    response = await loop.run_in_executor(
        None,
        chat,
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Generate the JSON summary."},
        ],
    )

    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1]
        if text.endswith("```"):
            text = text[:-3]

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"summary": text, "chart_type": "table", "insight": ""}
