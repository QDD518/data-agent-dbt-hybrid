# Project Progress: DataAgent-ChatBI

## Phase Overview

| Phase | Name | Status | Start | End |
|-------|------|--------|-------|-----|
| **Phase 1** | Environment + dbt Semantic Layer | ✅ Complete | 2026-05-10 | 2026-05-10 |
| Phase 2 | Backend Core (3 paths + orchestration) | ⬜ Pending | — | — |
| Phase 3 | Frontend (Chat UI + Charts) | ⬜ Pending | — | — |
| Phase 4 | Testing + Docs + Docker + Release | ⬜ Pending | — | — |

---

## Phase 1: Environment + dbt Semantic Layer ✅

**Completed**: 2026-05-10

### Deliverables
- [x] Python venv (3.12.8) at `venv/` with dbt-core 1.11.9 + dbt-postgres 1.10.0
- [x] Git repository initialized
- [x] Full directory structure (backend, frontend, dbt_project, tests, scripts, docs)
- [x] `.gitignore`, `.env.example`, `requirements.txt`, `docker-compose.yml`
- [x] E-commerce sample data: 95 orders, 12 customers, 20 products (seeds)
- [x] dbt project: 3 staging models, 3 marts models, time spine
- [x] dbt semantic layer: `semantic_models.yml` (2 semantic models) + `metrics.yml` (14 metrics)
- [x] `dbt parse` passes successfully

### Decisions & Notes
- **Python**: venv at project root, Python 3.12.8 (Windows), use `source venv/Scripts/activate`
- **PostgreSQL**: Docker-based (docker-compose), port 5432, schema `analytics` + `staging` + `raw`
- **dbt version**: dbt-core 1.11.9 — very recent. MetricFlow's time spine YAML config format is still evolving (deprecation warning about time_spine YAML config, non-blocking)
- **Data model**: Star schema — `fact_orders` with denormalized customer/product dimensions
- **Semantic layer**: 2 semantic models (orders, customers), 14 metrics (revenue, orders, customers, KPIs)
- **Time spine**: `metricflow_time_spine` generated via `generate_series()`, 2025-2026 date range
- **Docker**: Not accessible from current git-bash environment — user needs to start Docker Desktop separately for database operations

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

### Next: Phase 2 — Backend Core
- FastAPI skeleton + SSE support
- Metadata Service (dbt manifest parser)
- Path A: MetricFlow integration
- Path B: Text-to-SQL (LLM + RAG)
- Path C: Metadata QA (RAG)
- Intent router + orchestrator
