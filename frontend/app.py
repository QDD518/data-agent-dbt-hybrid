"""DataAgent-ChatBI — Streamlit frontend."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from frontend.utils.api import stream_chat, fetch_ontology
from frontend.components.chat import display_user_message, display_assistant_response
from frontend.components.ontology_graph import render_ontology

st.set_page_config(
    page_title="DataAgent-ChatBI",
    page_icon=None,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──
st.markdown("""
<style>
    /* Card-style buttons for sample questions */
    .sample-card button {
        width: 100%;
        min-height: 80px;
        border: 1px solid #E0E0E0;
        border-radius: 12px;
        background: #FFFFFF;
        padding: 16px;
        text-align: left;
        transition: all 0.2s ease;
        font-size: 0.95rem;
    }
    .sample-card button:hover {
        border-color: #1A73E8;
        box-shadow: 0 2px 12px rgba(26,115,232,0.12);
        transform: translateY(-1px);
    }
    /* Section dividers */
    .section-title {
        font-size: 0.85rem;
        font-weight: 600;
        color: #5F6368;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin: 16px 0 8px 0;
    }
    /* Empty state */
    .welcome-container {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        padding: 48px 0;
    }
    .welcome-title {
        font-size: 2rem;
        font-weight: 700;
        color: #202124;
        margin-bottom: 8px;
    }
    .welcome-subtitle {
        font-size: 1rem;
        color: #5F6368;
        margin-bottom: 32px;
    }
</style>
""", unsafe_allow_html=True)

# ── Session state ──
if "messages" not in st.session_state:
    st.session_state.messages = []
if "debug_sql" not in st.session_state:
    st.session_state.debug_sql = True
if "model_name" not in st.session_state:
    st.session_state.model_name = "deepseek-chat"


# ── Sidebar ──
with st.sidebar:
    st.title("DataAgent-ChatBI")
    st.caption("Chat BI — dbt + Ontology")

    st.divider()

    # Navigation
    st.markdown('<p class="section-title">Navigation</p>', unsafe_allow_html=True)
    st.page_link("app.py", label="Chat", icon=None)
    st.page_link("pages/data_dictionary.py", label="Data Dictionary", icon=None)

    st.divider()

    # Global controls
    st.markdown('<p class="section-title">Settings</p>', unsafe_allow_html=True)

    model = st.selectbox(
        "LLM Model",
        options=["deepseek-chat", "gpt-4o", "gpt-4o-mini", "claude-3-5-sonnet"],
        index=0,
        key="model_select",
    )
    st.session_state.model_name = model

    debug_sql = st.toggle("Show SQL", value=st.session_state.debug_sql, key="debug_toggle")
    st.session_state.debug_sql = debug_sql

    if st.button("Clear Chat History", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    st.divider()

    # Ontology explorer
    onto = fetch_ontology()
    render_ontology(onto)

    st.divider()
    st.caption("Backend: http://localhost:8000")
    st.caption("Data: E-commerce demo (95 orders, 12 customers, 20 products)")


# ── Sample questions ──
SAMPLES: list[tuple[str, str]] = [
    ("Metric Query", "上月营收是多少？"),
    ("Ontology Traversal", "North仓库有哪些商品需要补货？"),
    ("Exploratory", "哪个城市的客户平均客单价最高？"),
    ("Metadata Q&A", "revenue 指标是怎么计算的？"),
]


# ── Chat history ──
for msg in st.session_state.messages:
    if msg["role"] == "user":
        display_user_message(msg["content"])
    else:
        display_assistant_response(msg["events"])


# ── Empty state: welcome module ──
if not st.session_state.messages:
    st.markdown("""
    <div class="welcome-container">
        <div class="welcome-title">What would you like to know?</div>
        <div class="welcome-subtitle">Ask a question about your e-commerce data. The system routes intelligently across four paths.</div>
    </div>
    """, unsafe_allow_html=True)

    cols = st.columns(4)
    for i, (label, question) in enumerate(SAMPLES):
        with cols[i]:
            st.markdown('<div class="sample-card">', unsafe_allow_html=True)
            if st.button(f"**{label}**\n\n{question}", key=f"sample_{i}", use_container_width=True):
                st.session_state.pending_question = question
            st.markdown('</div>', unsafe_allow_html=True)


# ── Input ──
question = None

if "pending_question" in st.session_state and st.session_state.pending_question:
    question = st.session_state.pending_question
    st.session_state.pending_question = None

user_input = st.chat_input("Ask a question about your data...")
if user_input:
    question = user_input.strip()

if question:
    display_user_message(question)
    st.session_state.messages.append({"role": "user", "content": question})

    events = list(stream_chat(question))
    display_assistant_response(events)
    st.session_state.messages.append({"role": "assistant", "events": events})
    st.rerun()
