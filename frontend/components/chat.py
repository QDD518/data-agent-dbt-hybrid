"""Chat message rendering helpers."""

import streamlit as st
import pandas as pd


def display_user_message(message: str):
    with st.chat_message("user"):
        st.markdown(message)


def display_assistant_response(events: list[dict]):
    """Render the collected SSE events as a rich assistant message with reasoning steps."""
    with st.chat_message("assistant"):
        sql = None
        result = None
        done = None
        error = None
        path_label = None
        status_messages: list[str] = []
        context_docs: list[str] = []

        # First pass: collect events
        for event in events:
            etype = event.get("type", "")
            if etype == "status":
                status_messages.append(event)
            elif etype == "sql":
                sql = event.get("sql", "")
            elif etype == "result":
                result = event
            elif etype == "done":
                done = event
            elif etype == "error":
                error = event.get("message", "Unknown error")
            elif etype == "classified":
                path_label = event.get("path", "")

        # ── Reasoning process visualization ──
        path_display = {
            "metric_query": "Path A — Metric Query",
            "ontology_query": "Path B — Ontology Traversal",
            "exploratory": "Path C — Text-to-SQL",
            "metadata": "Path D — Metadata Q&A",
        }
        path_name = path_display.get(path_label, path_label or "Analyzing...")

        if status_messages:
            stages_seen = set()
            reasoning_lines: list[str] = []
            for evt in status_messages:
                stage = evt.get("stage", "")
                msg = evt.get("message", "")
                if stage not in stages_seen:
                    icon_map = {
                        "classifying": "Intent Router: classifying question...",
                        "classified": f"Routed to {path_name}",
                        "building_sql": "Building SQL...",
                        "executing": "Executing query...",
                        "interpreting": "Generating summary...",
                    }
                    reasoning_lines.append(icon_map.get(stage, msg))
                    stages_seen.add(stage)
            with st.expander(f"Processing — {path_name}", expanded=False):
                for line in reasoning_lines:
                    st.caption(f"{'✅' if path_name in line else '⏳'} {line}")

        # ── Error ──
        if error:
            st.error(error)
            return

        # ── SQL ──
        if sql and st.session_state.get("debug_sql", True):
            with st.expander("Generated SQL", expanded=False):
                st.code(sql, language="sql")

        # ── Result table ──
        if result:
            columns = result.get("columns", [])
            rows = result.get("rows", [])
            row_count = result.get("row_count", 0)
            truncated = result.get("truncated", False)
            elapsed = result.get("elapsed_ms", 0)

            if rows:
                df = pd.DataFrame(rows, columns=columns)
                st.caption(f"{row_count} rows · {elapsed:.0f}ms{' (truncated)' if truncated else ''}")
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Chart
                if done:
                    chart_type = (done.get("summary") or {}).get("chart_type", "bar")
                    from frontend.components.chart import render_chart
                    chart_html = render_chart(chart_type, columns, rows)
                    if chart_html:
                        from streamlit.components.v1 import html
                        html(chart_html, height=400)

        # ── NL summary ──
        if done:
            if done.get("summary"):
                summary = done["summary"]
                if isinstance(summary, dict):
                    st.markdown(f"**{summary.get('summary', '')}**")
                    insight = summary.get("insight", "")
                    if insight:
                        st.info(insight)
                else:
                    st.markdown(f"**{summary}**")
            elif done.get("answer"):
                st.markdown(done["answer"])
                sources = done.get("sources", [])
                if sources:
                    with st.expander("Sources"):
                        for s in sources:
                            st.text(s[:200] + "..." if len(s) > 200 else s)
