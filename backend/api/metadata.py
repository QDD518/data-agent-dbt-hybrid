"""API endpoint for fetching full metadata (models, metrics, ontology) for the Data Dictionary."""

from fastapi import APIRouter

from backend.metadata.parser import load_metadata
from backend.ontology.parser import load_ontology
from backend.semantic.registry import load_registry

router = APIRouter(tags=["metadata"])


@router.get("/api/metadata")
async def get_metadata():
    """Return combined metadata: dbt models + metrics + semantic models + ontology graph."""
    meta = load_metadata()
    onto = load_ontology()
    registry = load_registry()

    models = []
    for m in meta.models:
        cols = meta.columns_by_model.get(m["name"], [])
        models.append({
            "name": m["name"],
            "description": m.get("description", ""),
            "schema": m.get("schema", ""),
            "relation_name": m.get("relation_name", ""),
            "path": m.get("path", ""),
            "columns": [
                {"name": c["name"], "type": c.get("data_type", ""), "description": c.get("description", "")}
                for c in cols
            ],
        })

    metrics = []
    for m in meta.metrics:
        metrics.append({
            "name": m.get("name", ""),
            "description": m.get("description", ""),
            "type": m.get("type", ""),
            "type_params": m.get("type_params", {}),
            "filter": m.get("filter", ""),
            "label": m.get("label", ""),
        })

    semantic_models = []
    for sm in meta.semantic_models:
        semantic_models.append({
            "name": sm.get("name", ""),
            "description": sm.get("description", ""),
            "model": sm.get("model", ""),
            "entities": sm.get("entities", []),
            "dimensions": sm.get("dimensions", []),
            "measures": sm.get("measures", []),
        })

    return {
        "models": models,
        "metrics": metrics,
        "semantic_models": semantic_models,
        "ontology": onto.to_graph_dict(),
        "semantic_registry": registry.to_dict(),
    }
