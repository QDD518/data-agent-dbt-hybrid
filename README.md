# Data Agent — dbt Hybrid

**基于 dbt Semantic Layer 与 Palantir 本体论（Ontology）的四路径混合架构 Chat BI。**

本项目通过意图路由机制，将自然语言转化为确定性或受限的 SQL，旨在解决纯 Text-to-SQL 准确率低下，以及纯语义层缺乏跨对象查询能力的工程痛点。

用自然语言提问，系统智能路由：

- **指标类问题** → dbt 指标层确定性 SQL → 执行（绝不瞎编）
- **跨对象问题** → 本体论图遍历 → CTE 链式 SQL → 执行（多跳联动）
- **探索性问题** → LLM + dbt Schema + 本体论关系 → Text-to-SQL → 执行（灵活有约束）
- **元数据问题** → 查 dbt Docs 直接回答（免查询）

基于 dbt + PostgreSQL + Ontology + DeepSeek（或任何 OpenAI 兼容的 LLM）。

> [English Version →](README_EN.md)

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/)
[![dbt 1.11+](https://img.shields.io/badge/dbt-1.11+-orange.svg)](https://docs.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-green.svg)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-latest-red.svg)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 架构设计：dbt 语义层 + 本体论图模型

纯 Text-to-SQL 面临表结构幻觉和关联（JOIN）不可控的问题；而单纯的 dbt 语义层（如 MetricFlow）通常局限于单表聚合，扩展性受限。

DataAgent-ChatBI 在 dbt 语义层之上引入了**本体论图模型**，构建了四路径混合架构：

```
┌──────────────────────────────────────────────────────┐
│              本体论 (Business Graph)                  │
│        8 个对象类型 · 6 个链接类型 · 图遍历            │
│          "库存记录 —追踪→ 商品 —存放于→ 仓库"           │
└────────────────────────┬─────────────────────────────┘
                         │ 映射到
┌────────────────────────▼─────────────────────────────┐
│           dbt 语义层 (Physical Schema)                │
│       5 个语义模型 · 28 个指标 · MetricQueryBuilder     │
└────────────────────────┬─────────────────────────────┘
                         │ 查询
┌────────────────────────▼─────────────────────────────┐
│              PostgreSQL (chatbi_demo)                 │
│       17 个 dbt 模型 (OBT 宽表) · 8 个种子表           │
└──────────────────────────────────────────────────────┘

用户自然语言提问
    │
    ▼
┌──────────────────────────┐
│  意图路由器 (LLM)          │  分类: metric / ontology / exploratory / metadata
└──┬─────────┬─────────┬───┘
   │         │         │        │
   ▼         ▼         ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│路径 A│ │路径 D│ │路径 B│ │路径 C│
│指标  │ │本体论│ │Text- │ │元数据│
│查询  │ │遍历  │ │to-SQL│ │问答  │
└──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘
   │        │        │        │
   ▼        ▼        ▼        ▼
 语义元数据  图遍历    LLM+    RAG+LLM
 确定性SQL  CTE链式  RAG+本体论  直接回答
 单表聚合   SQL      生成SQL
   │        │        │        │
   └────────┼────────┼────────┘
            ▼
   ┌──────────────┐
   │   SQL 安全层  │  关键词黑名单 · 仅允许 SELECT · 行数限制
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │   SQL 执行器  │  只读事务 · 超时控制 · 自动序列化
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │  NL 解释器    │  LLM 摘要 + 图表推荐 + 洞察提取
   └──────┬───────┘
          ▼
   ┌──────────────┐
   │  SSE 流式推送  │  实时事件: classify → SQL → execute → done
   └──────────────┘
```

## 核心执行路径
### 路径 A — 指标查询（确定性构建）
当路由器识别为标准指标（如“上月营收”），系统提取参数并解析 semantic_manifest.json，直接生成单表聚合 SQL。此路径在 SQL 构建阶段不经过 LLM，实现逻辑层的 100% 确定性。 复杂的关联逻辑已在底层的 dbt OBT 宽表中处理完毕。

### 路径 B — 本体论图遍历（确定性跨表）
针对跨越多个业务对象的问题。路由器识别目标实体后，GraphTraverser 读取 ontology.yml。基于广度优先搜索（BFS）计算对象间的最短链接路径，并自动生成标准的 CTE 链式 SQL。
注：当前寻路逻辑基于最短路径假设，若业务存在多重复杂图边，需通过调整链接基数或表结构进行干预。

Denormalized 链接优化： 若相邻对象物理存储在同一张宽表（配置为 denormalized: true），系统在生成 SQL 时将自动跳过 JOIN，直接执行列合并。

### 路径 C — 探索性查询（受约束的 Text-to-SQL）
对于非标度量提问，LLM 将接收经过 RAG 检索的 dbt Schema 和本体论关系作为系统提示词（System Prompt）。利用本体论约束 LLM 的发散空间，显著降低非法 JOIN 产生的幻觉。

### 路径 D — 元数据 RAG 问答
针对数据定义与计算口径的提问。系统对 dbt manifest.json 及其描述字段进行检索，由 LLM 进行归纳输出，全程不触碰底层数据库。

### 意图路由器

一个轻量级 LLM prompt，将每个问题分类到四条路径之一，并提取结构化参数。路由器的 prompt 包含 28 个可用指标、所有维度和 8 个本体论对象类型，确保准确分类。

---

## 本体论 (Ontology) 设计与实现

dbt 语义层定义了度量（measures）与维度（dimensions），但缺乏对象关系的抽象。项目通过自定义的 ontology.yml 实现业务图谱映射：

```yaml
# 截取自 dbt_project/models/marts/ontology.yml
object_types:
  - name: Order
    primary_key: order_id
    table: "analytics_analytics.fact_orders"
    time_dimension: order_date
    # ...

  - name: Warehouse
    primary_key: warehouse_id
    table: "analytics_analytics.fact_inventory"

link_types:
  - name: stored_in          # InventoryRecord → Warehouse
    source: InventoryRecord
    target: Warehouse
    join_key:
      source_column: warehouse_id
      target_column: warehouse_id
    denormalized: true       # 指示目标对象位于同一物理表，阻断自联接
```

**设计要点**：
- **轻量级图谱计算**：摒弃图数据库依赖，采用原生 Python 字典存储邻接表。当前规模（8节点/6边）下 BFS 时间复杂度极低（$O(V+E)$）。
- **显式 JOIN 键**：明确多表关联规则，接管 LLM 的隐式推断。
- **`denormalized: true` 标记**：防止共享宽表时的自 JOIN 冗余。
- **属性按类型分类**：String / Numeric / Date / Boolean，帮助路由器理解过滤语义。

---

## 为什么用 dbt Semantic Layer 而不是 MetricFlow？

相比于 dbt 官方的 MetricFlow，本项目提供了开源环境下的可用替代方案，并增强了图谱能力：

| 特性 | MetricFlow | DataAgent-ChatBI |
|------|-----------|------------------|
| 依赖兼容性 | 限制严格（需 `click<8.3`，与 dbt-core 1.11 冲突） | 兼容 dbt-core 1.11+ 生态 |
| 执行环境 | 查询引擎需依赖 dbt Cloud 商业版 | 本地自定义 SQL Builder，完全开源 |
| 跨对象计算 | 支持有限，依赖底层视图 | 通过 `ontology.yml` 显式支持图遍历 |
| 对象关系建模 | 无 | 8 个对象类型 + 6 个链接类型，BFS 图遍历 |

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **四路径混合路由** | 指标查询 / 本体论遍历 / Text-to-SQL / 元数据问答 |
| **本体论图遍历** | 8 个对象类型，6 个链接类型，BFS 路径寻找 + CTE 链式 SQL |
| **Denormalized 链接优化** | 共享表对象无需 JOIN，自动合并列 |
| **SSE 流式推送** | 实时进度：分类中 → 图遍历 → 构建 SQL → 执行中 → 解释中 |
| **确定性指标 SQL** | 路径 A 指标查询零幻觉（解析 `semantic_manifest.json` 生成） |
| **LLM Text-to-SQL + RAG** | 探索性查询基于 dbt Schema + 本体论关系上下文 |
| **SQL 安全层** | 关键词黑名单、仅允许 SELECT、防多语句、行数限制 |
| **12 种过滤操作符** | eq/neq/gt/gte/lt/lte/in/between/like/is_null/is_not_null |
| **自动序列化** | Decimal → float、datetime → ISO 字符串，确保 JSON 兼容 |
| **中文分词 RAG** | CJK 字符二元分词 + 拉丁词分词的关键词检索（36 份文档，无需 Embedding API） |
| **前端本体论浏览器** | 侧边栏展示对象类型卡片，含属性和链接可视化 |
| **LLM 厂商无关** | 兼容 DeepSeek、OpenAI 或任何 OpenAI 兼容 API |

---

## 项目结构

```
├── dbt_project/                 # dbt 项目（多事实表模型 + 语义层 + 本体论）
│   ├── models/
│   │   ├── staging/             # 9 个 staging 视图
│   │   └── marts/               # 5 个 mart 模型 + 本体论定义
│   │       ├── fact_orders.sql   # OBT 宽表 (43 列)
│   │       ├── fact_inventory.sql # 库存事实表 (含 warehouse/supplier 维度)
│   │       ├── fact_marketing.sql # 营销活动事实表 (含 campaign 维度 + 衍生 KPI)
│   │       ├── dim_customers_rfm.sql # RFM 分层客户表
│   │       ├── cohort_monthly.sql   # 月度队列留存表
│   │       ├── semantic_models.yml  # 5 个语义模型 (orders, customers, inventory, marketing, customers_rfm)
│   │       ├── metrics.yml          # 28 个指标 (营收/订单/客户/库存/营销/RFM/队列)
│   │       └── ontology.yml         # 8 个对象类型 + 6 个链接类型
│   ├── seeds/                   # 8 个种子表 (orders 95行, inventory 48行, marketing 47行...)
│   └── target/
│       ├── manifest.json
│       └── semantic_manifest.json  # dbt parse 生成
│
├── backend/                     # FastAPI 后端 (Python 3.12)
│   ├── agent/
│   │   ├── router.py            # 四路径意图分类器 (LLM + 本体论对象列表)
│   │   └── orchestrator.py      # 四路径调度 + CrossModelQueryError 回退 + SSE 推送
│   ├── semantic/
│   │   └── query_builder.py     # 路径 A: 从 semantic_manifest 确定性生成单表聚合 SQL
│   ├── ontology/
│   │   ├── parser.py            # OntologyStore: 解析 ontology.yml，构建查找索引
│   │   └── traversal.py         # GraphTraverser: BFS 路径寻找 + CTE 链式 SQL 生成
│   ├── sql/
│   │   ├── security.py          # SQL 校验器 (关键词黑名单，仅允许 SELECT)
│   │   ├── generator.py         # 路径 B: LLM Text-to-SQL (含本体论关系上下文)
│   │   └── executor.py          # SQLAlchemy 只读执行器 + 序列化
│   ├── rag/
│   │   └── retriever.py         # 关键词检索器 (36 份文档: 22 dbt + 14 本体论)
│   ├── api/
│   │   ├── chat.py              # POST /api/chat (SSE 流式推送)
│   │   ├── health.py            # GET /api/health
│   │   └── ontology.py          # GET /api/ontology (节点 + 边 JSON)
│   ├── metadata/
│   │   └── parser.py            # dbt manifest + semantic_manifest 解析 + RAG 文档生成
│   └── llm/
│       └── client.py            # OpenAI 兼容 API 封装
│
├── frontend/                    # Streamlit 前端
│   ├── app.py                   # 入口: 聊天 UI + 本体论浏览器 + SSE 消费
│   ├── components/
│   │   ├── chat.py              # 富文本助手消息渲染 (SQL/结果/图表/摘要)
│   │   ├── chart.py             # pyecharts 柱状图/折线图/饼图 → HTML 嵌入
│   │   └── ontology_graph.py   # 本体论图可视化 (可展开对象卡片)
│   └── utils/
│       └── api.py               # httpx SSE 客户端 + fetch_ontology()
│
├── tests/                       # 145 个测试 (81 核心 + 64 本体论)
│   ├── test_ontology_parser.py  # 15 个: 解析、索引、RAG 文档、图 JSON
│   ├── test_ontology_traversal.py # 49 个: 过滤操作符、BFS、单表/多跳/去规范化 SQL
│   ├── test_security.py
│   ├── test_query_builder.py
│   ├── test_retriever.py
│   ├── test_router.py
│   ├── test_generator.py
│   ├── test_executor.py
│   └── test_integration.py
│
└── docs/
    └── architecture.md          # 完整架构文档 (dbt + 本体论双层级设计)
```

---

## 快速开始

### 环境要求

- Python 3.12+
- PostgreSQL 16+（或使用项目自带的 `docker-compose.yml`）
- dbt-core 1.11+
- LLM API Key（DeepSeek、OpenAI 或兼容 API）

### 1. 克隆项目

```bash
git clone https://github.com/QDD518/data-agent-dbt-hybrid.git
cd data-agent-dbt-hybrid
python -m venv venv
source venv/Scripts/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API Key 和 PostgreSQL 连接信息
```

必要的 `.env` 变量：

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | LLM API 密钥 |
| `OPENAI_BASE_URL` | API 基础 URL（DeepSeek: `https://api.deepseek.com`） |
| `LLM_MODEL` | 对话模型名 |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | PG 连接信息 |
| `POSTGRES_SCHEMA` | 默认 Schema（默认: `analytics`） |

### 3. 导入种子数据 & 构建 dbt 模型

```bash
cd dbt_project
dbt deps
dbt seed
dbt run
dbt parse          # 生成 manifest.json + semantic_manifest.json
cd ..
```

或使用 Docker PostgreSQL：
```bash
docker-compose up -d        # 启动 PG16, 创建 Schema
cd dbt_project && dbt seed && dbt run && dbt parse
```

### 4. 启动服务

**终端 1 — 后端：**
```bash
source venv/Scripts/activate
python -m backend.main
# → http://localhost:8000
# 启动日志: Metadata loaded (17 models). Ontology loaded (8 objects, 6 links).
```

**终端 2 — 前端：**
```bash
source venv/Scripts/activate
streamlit run frontend/app.py
# → http://localhost:8501
```

### 5. 开始提问

在 Streamlit 界面中尝试（侧边栏也展示了本体论对象浏览器）：

| 问题 | 路径 | 执行逻辑 |
|------|------|----------|
| 上月营收是多少？ | A | 从语义元数据确定性生成 SQL（指标 → 度量 → 表 → 列） |
| North仓库有哪些商品需要补货？ | D | 本体论图遍历 → CTE SQL（InventoryRecord → Product + Warehouse） |
| 哪个城市的客户平均客单价最高？ | B | LLM 结合 dbt Schema + 本体论 JOIN 约束生成 ad-hoc SQL |
| 每个品类的总库存价值 | A | 指标 + 维度分组聚合（total_inventory_value by product_category） |
| revenue 是怎么计算的？ | C | RAG 检索指标定义，LLM 直接回答 |

---

## 语义层工作原理

### 在 dbt YAML 中定义指标

```yaml
# dbt_project/models/marts/metrics.yml
metrics:
  - name: total_revenue
    label: "Total Revenue"
    type: simple
    type_params:
      measure: revenue          # 引用 semantic_models.yml 中的 measure
    filter: "{{ dim('status') }} = 'Completed'"
```

### 定义语义模型（度量 + 维度 + 实体）

```yaml
# dbt_project/models/marts/semantic_models.yml
semantic_models:
  - name: orders
    model: ref('fact_orders')
    entities:
      - name: order
        type: primary
        expr: order_id
      - name: customer
        type: foreign
        expr: customer_id
    dimensions:
      - name: order_date
        type: time
        type_params:
          time_granularity: day
      - name: product_category
        type: categorical
    measures:
      - name: revenue
        agg: sum
        expr: net_amount
```

### dbt parse → semantic_manifest.json → 确定性 SQL

```bash
dbt parse  # 校验并输出 manifest 文件
# 路径 A 生成: SELECT SUM(net_amount) FROM analytics_analytics.fact_orders WHERE status = 'Completed'
# 路径 D 使用 ontology.yml 中的对象-链接图进行跨对象遍历
```

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 数据转换 | dbt-core 1.11（9 个 staging 视图 → 6 个 mart 表） |
| 语义层 | dbt Semantic Models + Metrics（5 个模型, 28 个指标） |
| 本体论 | 自定义 YAML 图模型（8 个对象类型, 6 个链接类型） |
| 查询生成 (Path A) | 自定义 Python MetricQueryBuilder（解析 semantic_manifest.json） |
| 查询生成 (Path D) | 自定义 Python GraphTraverser（BFS + CTE 链式 SQL） |
| 查询生成 (Path B) | LLM Text-to-SQL（含 dbt Schema + 本体论关系 RAG 上下文） |
| 数据库 | PostgreSQL 16（SQLAlchemy + psycopg2） |
| 后端 | FastAPI + SSE 流式传输 + 4 路径编排器 |
| 前端 | Streamlit + pyecharts + 本体论对象浏览器 |
| 大模型 | DeepSeek V4 / OpenAI / 兼容 API |
| RAG | 关键词重叠度检索（CJK 二元分词 + 拉丁词分词, 36 份文档） |
| 安全 | SQL 关键词黑名单、仅允许 SELECT、行数限制、超时控制 |
| 测试 | 145 个测试 (pytest), 4 个 PG 依赖跳过 |

---

## License

MIT — 详见 [LICENSE](LICENSE) 文件。

---

## 作者

**QDD518** — [github.com/QDD518](https://github.com/QDD518)

*作为开源 Chat BI 参考架构构建。欢迎贡献和反馈。*
