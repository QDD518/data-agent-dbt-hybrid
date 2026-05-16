"""API endpoint for fetching the ontology graph."""

from fastapi import APIRouter

from backend.ontology.parser import load_ontology

router = APIRouter(tags=["ontology"])


@router.get("/api/ontology")
async def get_ontology():
    """Return the full ontology graph (nodes + edges) for frontend visualization."""
    store = load_ontology()
    return store.to_graph_dict()
