# Project Progress: DataAgent-ChatBI

## Phase Overview

| Phase | Name | Status | Start | End |
|-------|------|--------|-------|-----|
| **Phase 1** | Environment + dbt Semantic Layer | ✅ Complete | 2026-05-10 | 2026-05-10 |
| **Phase 2** | Backend Core (3 paths + orchestration) | ✅ Complete | 2026-05-12 | 2026-05-13 |
| **Phase 3** | Frontend (Chat UI + Charts) | ✅ Complete | 2026-05-13 | 2026-05-13 |
| Phase 4 | Testing + Docs + Docker + Release | ⬜ Pending | — | — |

---

## Phase 3: Frontend (Chat UI + Charts) ✅

**Completed**: 2026-05-13

### Deliverables (7 Python files)
- [x] `frontend/app.py` — Streamlit entry, sidebar with sample questions
- [x] `frontend/utils/api.py` — SSE consumer via httpx streaming
- [x] `frontend/components/chat.py` — Message rendering: user bubble, assistant with SQL/results/summary
- [x] `frontend/components/chart.py` — pyecharts rendering (bar/line/pie)
- [x] Session state for message history
- [x] Intent classification display
- [x] SQL code block with syntax highlighting

### UI Layout
- **Sidebar**: architecture explanation, sample questions (5 presets covering all 3 paths)
- **Main area**: chat bubbles with rich assistant responses
  - Collapsible intent classification
  - Expandable SQL block
  - Data table (st.dataframe)
  - Chart (pyecharts HTML via st.components.v1.html)
  - NL summary + insight

### Startup
```bash
# Terminal 1: Backend
source venv/Scripts/activate && python -m backend.main

# Terminal 2: Frontend
source venv/Scripts/activate && streamlit run frontend/app.py
```

### Known Limitations
- Streamlit is re-run based — SSE events are collected and rendered all at once (not token-by-token streaming). The backend streams on the wire, but the UI renders the complete response.
- Requires backend running on localhost:8000.
- Charts use pyecharts + st.components.v1.html (iframe-based). ✅

**Completed**: 2026-05-10

### Deliverables
- [x] Python venv (3.12.8) at `venv/` with dbt-core 1.11.9 + dbt-postgres 1.10.0
- [x] Git repository initialized
- [x] Full directory structure (backend, frontend, dbt_project, tests, scripts, docs)
- [x] `.gitignore`, `.env.example`, `requirements.txt`, `docker-compose.yml`
- [x] E-commerce sample data: 95 orders, 12 customers, 20 products (seeds)
- [x] dbt project: 3 staging models, 3 marts models, time spine
- [x] dbt semantic layer: `semantic_models.yml` (2 semantic models) + `metrics.yml` (12 metrics)
- [x] `dbt parse` passes successfully

### Decisions & Notes
- **Python**: venv at project root, Python 3.12.8 (Windows), use `source venv/Scripts/activate`
- **PostgreSQL**: Native Windows install PG16 port 5433, schema `analytics` + `staging` + `raw`. PG17 was removed; PG16 used natively (no Docker/WSL).
- **dbt version**: dbt-core 1.11.9 — very recent. MetricFlow's time spine YAML config format is still evolving (deprecation warning about time_spine YAML config, non-blocking)
- **Data model**: Star schema — `fact_orders` (OBT wide table) with denormalized customer/product dimensions
- **Semantic layer**: 2 semantic models (orders, customers), 12 metrics (revenue, orders, customers, KPIs)
- **Time spine**: `metricflow_time_spine` generated via `generate_series()`, 2025-2026 date range

### Known Issues (non-blocking)
- MetricFlow time spine YAML config deprecation warning — cosmetic only, `dbt parse` succeeds
- Docker not available in current shell — `dbt seed`/`dbt run` require PostgreSQL container to be started separately

### Data Model
```
raw_orders (seed)     raw_customers (seed)     raw_products (seed)
     ↓                      ↓                        ↓
stg_orders (view)    stg_customers (view)    stg_products (view)
     ↓                      ↓                        ↓
     └──────────────────────┼────────────────────────┘
                            ↓
                     fact_orders (table)
                  dim_customers (table)
                   dim_products (table)
                            ↓
                  semantic_models.yml
                       metrics.yml
                            ↓
                      MetricFlow
```

---

## Phase 2: Backend Core (3 paths + orchestration) ✅

**Completed**: 2026-05-13

### Key Architecture Decision

**MetricFlow PyPI package is dead** — incompatible with dbt-core 1.11.9 (click version conflict). dbt Labs moved semantic layer querying to dbt Cloud.  

**Solution**: Built custom "last-mile SQL aggregator" that parses `semantic_manifest.json` metadata and generates SQL deterministically. Same logic as MetricFlow internally — uses exact column names, aggregation functions, and filters from dbt YAML definitions. 100% accurate for metric queries.

**Joins are handled in dbt models** (OBT `fact_orders`), semantic layer only does `SELECT agg ... GROUP BY ... WHERE ...`.

### Deliverables (22 Python files)

**Core infrastructure:**
- [x] FastAPI app with CORS, SSE (sse-starlette), health check
- [x] Configuration via `pydantic-settings` with `.env` support
- [x] PostgreSQL: native Windows install, port 5433, database `chatbi_demo`

**Metadata Service** (`backend/metadata/parser.py`):
- [x] Parses `manifest.json` → 8 models with 65+ columns
- [x] Parses `semantic_manifest.json` → 2 semantic models, 12 metrics
- [x] Generates 22 RAG documents for ChromaDB

**SQL Executor + Security** (`backend/sql/`):
- [x] SQLAlchemy 2.0 read-only executor with connection pool
- [x] Security validator: keyword blocklist, SELECT-only, multi-statement blocking
- [x] Row limit + statement timeout

**Path A — Metric Query** (`backend/semantic/query_builder.py`):
- [x] Resolves metric → measure → semantic model → table → columns
- [x] Generates last-mile aggregation SQL: SELECT agg(expr) + GROUP BY dim + WHERE filter
- [x] Supports time granularity (day/week/month), relative time ranges
- [x] Dimension scoping per semantic model (no cross-model collision)
- [x] Filter deduplication

**Path B — Exploratory Text-to-SQL** (`backend/sql/generator.py`):
- [x] LLM + RAG context → ad-hoc SQL generation
- [x] Prompt includes dbt model/column metadata

**Path C — Metadata QA** (`backend/agent/orchestrator.py`):
- [x] RAG retrieval + LLM direct answer (no SQL)

**RAG Module** (`backend/rag/`):
- [x] ChromaDB PersistentClient at `chroma_db/`
- [x] OpenAI `text-embedding-3-small` embeddings
- [x] Lazy indexing on first retrieval

**Intent Router** (`backend/agent/router.py`):
- [x] LLM-driven 3-way classifier: metric_query / exploratory / metadata
- [x] Extracts metric names, dimensions, time_range

**Chat Orchestrator** (`backend/agent/orchestrator.py`):
- [x] SSE-streaming pipeline: classify → build SQL → execute → interpret
- [x] Result Interpreter: NL summary + chart type recommendation

### Decisions & Notes
- **Semantic layer scope**: Last-mile aggregation only. Complex joins pre-resolved in dbt models (OBT fact_orders). This avoids graph traversal complexity.
- **Cross-model queries**: Rejected by design. If a metric is on `fact_orders` and another on `dim_customers`, the builder errors. This is intentional — each query hits one table.
- **LLM dependency**: All 3 paths depend on LLM (router, Path B generator, interpreter). Without OPENAI_API_KEY, only SQL generation (Path A dry-run) and SQL execution work.
- **ChromaDB**: Lazy initialization — first RAG call triggers embedding + indexing. Requires OpenAI API key.

### File Tree
```
backend/
├── main.py                    # FastAPI + lifespan
├── config.py                  # Settings from .env
├── api/
│   ├── chat.py                # POST /api/chat (SSE stream)
│   └── health.py              # GET /api/health
├── agent/
│   ├── router.py              # Intent Router (LLM classifier)
│   └── orchestrator.py        # 3-path dispatch + result interpreter
├── semantic/
│   └── query_builder.py       # Path A: last-mile SQL aggregator
├── sql/
│   ├── executor.py            # SQLAlchemy read-only executor
│   ├── security.py            # SQL validation
│   └── generator.py           # Path B: LLM Text-to-SQL
├── rag/
│   ├── indexer.py             # ChromaDB indexing
│   └── retriever.py           # Vector search
├── metadata/
│   └── parser.py              # dbt manifest.json parser
└── llm/
    └── client.py              # OpenAI API wrapper
```

### Next: Phase 3 — Frontend (Chat UI + Charts)
- Streamlit chat interface
- SSE event consumption
- ECharts/pyecharts chart rendering
- 3-path response display
