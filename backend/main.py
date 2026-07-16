import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: pre-load metadata
    logger.info("Loading dbt metadata...")
    from backend.metadata.parser import load_metadata
    load_metadata()
    logger.info("Metadata loaded (%d models).", len(load_metadata().models))

    # Build the canonical registry once at startup. This validates that dbt
    # artifacts and ontology.yml describe the same physical data contract.
    logger.info("Building semantic registry...")
    from backend.semantic.registry import load_registry
    registry = load_registry()
    logger.info(
        "Semantic registry loaded (%d metrics, %d entities, %d relationships).",
        len(registry.metrics), len(registry.entities), len(registry.relationships),
    )

    # RAG uses keyword-based retrieval (no embedding API dependency)
    logger.info("Server ready.")

    yield
    logger.info("Shutting down.")


app = FastAPI(
    title="DataAgent-ChatBI",
    description="Chat BI powered by dbt Semantic Layer + Text-to-SQL + RAG",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from backend.api.health import router as health_router
from backend.api.chat import router as chat_router
from backend.api.ontology import router as ontology_router
from backend.api.metadata import router as metadata_router

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(ontology_router)
app.include_router(metadata_router)


if __name__ == "__main__":
    import uvicorn
    import os

    is_prod = settings.app_env == "production"
    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=not is_prod,
        workers=os.cpu_count() if is_prod else 1,
    )
