"""Ontology graph visualization — renders Object Types and Link Types as cards."""

import streamlit as st


def render_ontology(ontology_data: dict | None):
    """Render the ontology graph in the sidebar."""
    if not ontology_data:
        st.warning("Ontology not available. Make sure the backend is running.")
        return

    nodes = ontology_data.get("nodes", [])
    edges = ontology_data.get("edges", [])

    st.markdown("###  Business Ontology")
    st.caption(f"{len(nodes)} Object Types · {len(edges)} Link Types")

    # Show each object type with its outbound links
    for node in nodes:
        color = node.get("color", "#888")
        icon = node.get("icon", "")
        label = node.get("label", node["id"])
        obj_id = node["id"]

        # Find outbound links
        out_links = [e for e in edges if e["source"] == obj_id]
        in_links = [e for e in edges if e["target"] == obj_id]

        with st.expander(f"{label} ({obj_id})", expanded=False):
            # Object info
            st.markdown(
                f"<span style='color:{color};font-size:1.2em'>"
                f"• {node.get('description','')}</span>",
                unsafe_allow_html=True,
            )
            st.caption(f"Table: `{node.get('table','')}` | Key: `{node.get('primary_key','')}`")

            # Properties
            props = node.get("properties", [])
            if props:
                st.caption(
                    ", ".join(
                        f"`{p['name']}`" for p in props[:8]
                    )
                    + ("..." if len(props) > 8 else "")
                )

            # Outbound links
            if out_links:
                st.markdown("**Outbound Links:**")
                for link in out_links:
                    dn = " (denormalized — no JOIN)" if link.get("denormalized") else ""
                    st.caption(
                        f"→ **{link['label']}** → {link['target']} "
                        f"via `{link.get('source_column','')}` = `{link.get('target_column','')}`"
                        f"{dn}"
                    )

            # Inbound links
            if in_links:
                st.markdown("**Inbound Links:**")
                for link in in_links:
                    st.caption(f"← {link['source']} → **{link['label']}**")
