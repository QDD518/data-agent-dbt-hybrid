import json
from pathlib import Path
from functools import lru_cache

from backend.config import settings


class MetadataStore:
    """Parsed dbt manifest + semantic manifest, held in memory for fast access."""

    def __init__(self):
        self.models: list[dict] = []
        self.metrics: list[dict] = []
        self.semantic_models: list[dict] = []
        self.model_by_name: dict[str, dict] = {}
        self.columns_by_model: dict[str, list[dict]] = {}

    def to_rag_documents(self) -> list[str]:
        """Produce text chunks for embedding into ChromaDB."""
        docs: list[str] = []

        for model in self.models:
            cols = self.columns_by_model.get(model["name"], [])
            col_str = "; ".join(f"{c['name']}: {c.get('description','')}" for c in cols)
            docs.append(
                f"Table {model['name']} ({model.get('schema','')}): "
                f"{model.get('description','')}. Columns: {col_str}"
            )

        for metric in self.metrics:
            docs.append(
                f"Metric {metric['name']}: {metric.get('description','')} "
                f"(type={metric.get('type','')})"
            )

        for sm in self.semantic_models:
            dims = [d["name"] for d in sm.get("dimensions", [])]
            meas = [m["name"] for m in sm.get("measures", [])]
            docs.append(
                f"Semantic model {sm['name']}: {sm.get('description','')}. "
                f"Dimensions: {', '.join(dims)}. Measures: {', '.join(meas)}."
            )

        # Append ontology documents for cross-model join guidance
        try:
            from backend.ontology.parser import load_ontology
            onto = load_ontology()
            docs.extend(onto.to_rag_documents())
        except Exception:
            pass

        return docs


@lru_cache(maxsize=1)
def load_metadata() -> MetadataStore:
    """Parse dbt manifest and semantic manifest. Cached in-process."""
    store = MetadataStore()
    project_dir = Path(settings.dbt_project_dir)
    target_dir = project_dir / "target"

    # ── manifest.json: models, columns ──
    manifest_path = target_dir / "manifest.json"
    if manifest_path.exists():
        manifest = _load_json(manifest_path)
        nodes = manifest.get("nodes", {})

        for node_key, node in nodes.items():
            if node.get("resource_type") != "model":
                continue
            name = node.get("name", "")
            model_info = {
                "name": name,
                "description": node.get("description", ""),
                "schema": node.get("schema", ""),
                "relation_name": node.get("relation_name", ""),
                "path": node.get("original_file_path", ""),
            }
            store.models.append(model_info)
            store.model_by_name[name] = model_info

            columns = []
            for col_name, col_data in node.get("columns", {}).items():
                columns.append({
                    "name": col_name,
                    "description": col_data.get("description", ""),
                    "data_type": col_data.get("data_type", ""),
                })
            store.columns_by_model[name] = columns

    # ── semantic_manifest.json: semantic models, metrics ──
    semantic_path = target_dir / "semantic_manifest.json"
    if semantic_path.exists():
        sm = _load_json(semantic_path)
        store.semantic_models = sm.get("semantic_models", [])
        store.metrics = sm.get("metrics", [])

    return store


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
