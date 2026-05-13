"""Chat message rendering helpers."""

import streamlit as st
import pandas as pd


def display_user_message(message: str):
    with st.chat_message("user"):
        st.markdown(message)


def display_assistant_response(events: list[dict]):
    """Render the collected SSE events as a rich assistant message."""
    with st.chat_message("assistant"):
        sql = None
        result = None
        done = None
        error = None
        status_messages: list[str] = []
        context_docs: list[str] = []

        for event in events:
            etype = event.get("type", "")

            if etype == "status":
                status_messages.append(event.get("message", ""))
                with st.status(event.get("message", ""), expanded=False):
                    st.text(f"Stage: {event.get('stage', '')}")

            elif etype == "sql":
                sql = event.get("sql", "")
                with st.expander("SQL", expanded=False):
                    st.code(sql, language="sql")

            elif etype == "result":
                result = event

            elif etype == "done":
                done = event

            elif etype == "error":
                error = event.get("message", "Unknown error")
                st.error(error)

            elif etype == "context":
                context_docs = event.get("documents", [])

            elif etype == "classified":
                path = event.get("path", "")
                intent = event.get("intent", {})
                with st.expander("Intent Classification", expanded=False):
                    st.json({"path": path, "metrics": intent.get("metric_names", [])})

        # ── Render results ──
        if result:
            columns = result.get("columns", [])
            rows = result.get("rows", [])
            row_count = result.get("row_count", 0)
            truncated = result.get("truncated", False)
            elapsed = result.get("elapsed_ms", 0)

            if rows:
                df = pd.DataFrame(rows, columns=columns)
                st.caption(f"{row_count} rows in {elapsed:.0f}ms{' (truncated)' if truncated else ''}")
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Chart
                if done:
                    chart_type = (done.get("summary") or {}).get("chart_type", "bar")
                    from frontend.components.chart import render_chart
                    chart_html = render_chart(chart_type, columns, rows)
                    if chart_html:
                        from streamlit.components.v1 import html
                        html(chart_html, height=400)

        # ── Render NL summary ──
        if done and done.get("summary"):
            summary = done["summary"]
            if isinstance(summary, dict):
                st.markdown(f"**{summary.get('summary', '')}**")
                insight = summary.get("insight", "")
                if insight:
                    st.info(insight)
            else:
                st.markdown(f"**{summary}**")

        elif done and done.get("answer"):
            st.markdown(done["answer"])
            sources = done.get("sources", [])
            if sources:
                with st.expander("Sources"):
                    for s in sources:
                        st.text(s[:200] + "..." if len(s) > 200 else s)
