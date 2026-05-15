"""DataAgent-ChatBI — Streamlit frontend."""

import sys
from pathlib import Path

# Ensure project root is on PYTHONPATH (for `from frontend.xxx` imports)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from frontend.utils.api import stream_chat
from frontend.components.chat import display_user_message, display_assistant_response

st.set_page_config(
    page_title="DataAgent-ChatBI",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state ──
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {"role": "user"|"assistant", "events": [...]}


# ── Sidebar ──
with st.sidebar:
    st.title("DataAgent-ChatBI")
    st.markdown("Chat BI powered by dbt Semantic Layer")
    st.divider()

    st.markdown("### How it works")
    st.markdown("""
    - **Path A** — Metric queries via semantic layer (100% accurate)
    - **Path B** — Exploratory queries via Text-to-SQL + RAG
    - **Path C** — Metadata Q&A via dbt docs
    """)

    st.divider()
    st.markdown("### Sample Questions")
    samples = [
        ("Metric", "上月营收是多少？"),
        ("Metric + Dim", "每个品类的销售额"),
        ("Metric + Time", "过去一周每天的订单数"),
        ("Exploratory", "哪个城市的客户平均客单价最高？"),
        ("Metadata", "revenue 指标是怎么计算的？"),
    ]
    for path, q in samples:
        if st.button(f"[{path}] {q}", key=f"sample_{q}"):
            st.session_state.pending_question = q

    st.divider()
    st.caption("Backend: http://localhost:8000")
    st.caption("Data: E-commerce demo (95 orders, 12 customers, 20 products)")


# ── Chat history ──
for msg in st.session_state.messages:
    if msg["role"] == "user":
        display_user_message(msg["content"])
    else:
        display_assistant_response(msg["events"])


# ── Input ──
question = None

# Check for pending question from sidebar
if "pending_question" in st.session_state and st.session_state.pending_question:
    question = st.session_state.pending_question
    st.session_state.pending_question = None

# Chat input
user_input = st.chat_input("Ask a question about your data...")
if user_input:
    question = user_input.strip()


if question:
    # Display user message
    display_user_message(question)
    st.session_state.messages.append({"role": "user", "content": question})

    # Stream from backend
    with st.spinner("Thinking..."):
        events = list(stream_chat(question))

    # Display assistant response
    display_assistant_response(events)
    st.session_state.messages.append({"role": "assistant", "events": events})
    st.rerun()
