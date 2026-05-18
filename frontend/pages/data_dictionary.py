"""Data Dictionary — browse dbt models, metrics, and Ontology objects."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import streamlit as st
import pandas as pd

from frontend.utils.api import fetch_metadata

st.set_page_config(page_title="Data Dictionary", page_icon=None, layout="wide")

st.title("Data Dictionary")
st.caption("Browse dbt models, business metrics, and Ontology objects.")

# ── Load data ──
@st.cache_data(ttl=300)
def load_data():
    return fetch_metadata()

data = load_data()

if not data:
    st.error("Unable to connect to backend. Make sure the backend is running at http://localhost:8000")
    st.stop()

models = data.get("models", [])
metrics = data.get("metrics", [])
semantic_models = data.get("semantic_models", [])
ontology = data.get("ontology", {})
onto_nodes = ontology.get("nodes", [])
onto_edges = ontology.get("edges", [])

# ── Tabs ──
tab_overview, tab_tables, tab_metrics, tab_objects, tab_links = st.tabs([
    "Overview",
    "Tables & Columns",
    "Business Metrics",
    "Ontology Graph",
    "Ontology Links",
])

# ═══════════════════════════════════════════════════════════════
# Tab 1: Overview
# ═══════════════════════════════════════════════════════════════
with tab_overview:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("dbt Models", len(models))
    col2.metric("Metrics", len(metrics))
    col3.metric("Object Types", len(onto_nodes))
    col4.metric("Link Types", len(onto_edges))

    st.divider()

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("dbt Models")
        model_rows = []
        for m in sorted(models, key=lambda x: x["name"]):
            cols_info = m.get("columns", [])
            model_rows.append({
                "Model": m["name"],
                "Cols": len(cols_info),
                "Schema": m.get("schema", ""),
            })
        st.dataframe(pd.DataFrame(model_rows), use_container_width=True, hide_index=True)

    with col_right:
        st.subheader("Ontology Object Types")
        obj_rows = []
        for node in onto_nodes:
            out_links = [e for e in onto_edges if e["source"] == node["id"]]
            obj_rows.append({
                "Object": node.get("label", node["id"]),
                "ID": node["id"],
                "Table": node.get("table", ""),
                "Links": len(out_links),
            })
        st.dataframe(pd.DataFrame(obj_rows), use_container_width=True, hide_index=True)

# ═══════════════════════════════════════════════════════════════
# Tab 2: Tables & Columns
# ═══════════════════════════════════════════════════════════════
with tab_tables:
    model_names = sorted([m["name"] for m in models])
    selected_model = st.selectbox("Select a model", model_names, key="table_select")

    if selected_model:
        model = next((m for m in models if m["name"] == selected_model), None)
        if model:
            st.subheader(model["name"])
            if model.get("description"):
                st.markdown(model["description"])
            st.caption(f"Schema: `{model.get('schema', '')}` | Relation: `{model.get('relation_name', '')}`")

            columns = model.get("columns", [])
            if columns:
                col_rows = [{"Column": c["name"], "Type": c.get("type", ""), "Description": c.get("description", "") or "—"} for c in columns]
                st.dataframe(pd.DataFrame(col_rows), use_container_width=True, hide_index=True)
            else:
                st.info("No column metadata available for this model.")

# ═══════════════════════════════════════════════════════════════
# Tab 3: Business Metrics — DataFrame with search
# ═══════════════════════════════════════════════════════════════
with tab_metrics:
    search = st.text_input("Search metrics", placeholder="Filter by name, label, or measure...", key="metric_search")

    # Build flat metric rows
    metric_rows = []
    for m in metrics:
        tp = m.get("type_params", {})
        metric_rows.append({
            "Metric Name": m["name"],
            "Label": m.get("label", ""),
            "Type": m.get("type", "—"),
            "Measure": tp.get("measure", "—") if tp else "—",
            "Filter": m.get("filter", ""),
            "Description": m.get("description", ""),
        })

    df_metrics = pd.DataFrame(metric_rows)

    if search:
        q = search.lower()
        mask = (
            df_metrics["Metric Name"].str.lower().str.contains(q, na=False)
            | df_metrics["Label"].str.lower().str.contains(q, na=False)
            | df_metrics["Measure"].str.lower().str.contains(q, na=False)
            | df_metrics["Description"].str.lower().str.contains(q, na=False)
        )
        df_metrics = df_metrics[mask]

    st.caption(f"Showing {len(df_metrics)} of {len(metrics)} metrics")
    st.dataframe(df_metrics, use_container_width=True, hide_index=True,
                 column_config={
                     "Metric Name": st.column_config.TextColumn(width="medium"),
                     "Label": st.column_config.TextColumn(width="medium"),
                     "Filter": st.column_config.TextColumn(width="medium"),
                     "Description": st.column_config.TextColumn(width="large"),
                 })

# ═══════════════════════════════════════════════════════════════
# Tab 4: Ontology Graph — Directed graph via Graphviz
# ═══════════════════════════════════════════════════════════════
with tab_objects:
    st.caption(f"{len(onto_nodes)} Object Types · {len(onto_edges)} Link Types")

    import graphviz

    dot = graphviz.Digraph(format="svg")
    dot.attr(rankdir="LR", bgcolor="#FAFBFC", pad="0.5")
    dot.attr("node", shape="box", style="filled,rounded", fillcolor="#FFFFFF", color="#1A73E8",
             fontname="Helvetica", fontsize="12", penwidth="2", margin="0.2,0.1")
    dot.attr("edge", fontname="Helvetica", fontsize="10", color="#5F6368", penwidth="1.5")

    for node in onto_nodes:
        label = node.get("label", node["id"])
        table_name = node.get("table", "").split(".")[-1]
        node_label = f"{label}\n({node['id']})\n[{table_name}]"
        color = node.get("color", "#1A73E8")
        dot.node(node["id"], node_label, color=color, fontcolor="#202124")

    for edge in onto_edges:
        style = "dashed" if edge.get("denormalized") else "solid"
        label = edge.get("label", edge.get("id", ""))
        if edge.get("denormalized"):
            label += " (inline)"
        dot.edge(edge["source"], edge["target"], label=label, style=style)

    svg_data = dot.pipe().decode("utf-8")
    # Strip XML declaration for inline embed
    if svg_data.startswith("<?xml"):
        svg_data = svg_data[svg_data.find("<svg"):]

    st.components.v1.html(f"""
    <div style="display:flex;justify-content:center;background:#FAFBFC;border:1px solid #E0E0E0;border-radius:12px;padding:16px;">
        {svg_data}
    </div>
    """, height=540, scrolling=True)

    st.caption("**Legend:** Solid line = JOIN required · Dashed line = Denormalized (no JOIN) · Arrow = relationship direction")

    # Detail cards below graph
    st.divider()
    st.subheader("Object Details")
    obj_cols = st.columns(min(len(onto_nodes), 4))
    for i, node in enumerate(onto_nodes):
        col_idx = i % len(obj_cols)
        with obj_cols[col_idx]:
            out = [e for e in onto_edges if e["source"] == node["id"]]
            in_ = [e for e in onto_edges if e["target"] == node["id"]]
            with st.container(border=True):
                st.markdown(f"**{node.get('label', node['id'])}**")
                st.caption(f"`{node.get('table', '')}` | PK: `{node.get('primary_key', '')}`")
                props = node.get("properties", [])
                if props:
                    st.caption(", ".join(f"`{p['name']}`" for p in props[:6]) + ("..." if len(props) > 6 else ""))
                if out:
                    st.caption("→ " + ", ".join(f"*{e['label']}* → {e['target']}" + (" (inline)" if e.get('denormalized') else "") for e in out))
                if in_:
                    st.caption("← " + ", ".join(f"{e['source']} → *{e['label']}*" for e in in_))

# ═══════════════════════════════════════════════════════════════
# Tab 5: Ontology Links — Table
# ═══════════════════════════════════════════════════════════════
with tab_links:
    st.caption(f"{len(onto_edges)} Link Types")

    if onto_edges:
        link_rows = []
        for link in onto_edges:
            link_rows.append({
                "Link Name": link.get("label", link.get("id", "")),
                "Source → Target": f"{link.get('source', '')} → {link.get('target', '')}",
                "Join Key": f"{link.get('source_column', '')} = {link.get('target_column', '')}",
                "Cardinality": link.get("cardinality", ""),
                "Denormalized": "" if link.get("denormalized") else "—",
            })
        st.dataframe(pd.DataFrame(link_rows), use_container_width=True, hide_index=True,
                     column_config={
                         "Link Name": st.column_config.TextColumn(width="medium"),
                         "Source → Target": st.column_config.TextColumn(width="large"),
                         "Join Key": st.column_config.TextColumn(width="medium"),
                     })
