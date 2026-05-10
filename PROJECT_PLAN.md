# Chat BI 系统项目计划书

## 一、项目概述

### 1.1 项目名称
**DataAgent-ChatBI** — 基于 dbt 语义层 + PostgreSQL 的智能对话式 BI 系统

### 1.2 项目定位
构建一个开源的对话式商业智能系统。核心思路：**不依赖 LLM 直接生成 SQL**，而是利用 dbt Semantic Layer（MetricFlow）作为"可信 SQL 生成引擎"来处理标准化指标查询，仅在用户提出探索性/即席问题时降级到 LLM Text-to-SQL。

项目将发布到 GitHub 作为个人案例作品。

### 1.3 核心价值
- **指标查询零幻觉**：预定义指标通过 MetricFlow 生成 SQL，100% 语义正确
- **探索性查询灵活**：非标准化问题由 LLM + dbt 元数据上下文处理
- **可复现、可审计**：每条 SQL 透明可查，指标口径有 dbt 版本管理
- **轻量自托管**：不依赖 dbt Cloud，完全基于 dbt-core + MetricFlow OSS

---

## 二、核心路径评估：Text-to-SQL vs dbt 语义层 vs 混合方案

### 2.1 三种方案对比

```
方案 A: 纯 Text-to-SQL
  用户问题 ──→ LLM ──→ SQL ──→ 执行
  上下文: dbt manifest.json 作为 RAG 知识库
```

```
方案 B: 纯 dbt 语义层 (MetricFlow)
  用户问题 ──→ 意图识别 ──→ MetricFlow API ──→ SQL ──→ 执行
  上下文: semantic_models + metrics YAML 定义
```

```
方案 C: 混合方案 (推荐)
  用户问题 ──→ 意图分类器 (LLM)
                ├── 指标类问题 ──→ MetricFlow ──→ SQL ──→ 执行  (零幻觉)
                ├── 探索性问题 ──→ LLM + RAG ──→ SQL ──→ 执行  (灵活)
                └── 元数据问题 ──→ 直接回答 (dbt docs)           (免查询)
```

### 2.2 详细评估

| 评估维度 | 纯 Text-to-SQL | 纯 MetricFlow | **混合方案（推荐）** |
|----------|:-------------:|:------------:|:-----------------:|
| **指标查询准确率** | 70-85%（依赖 LLM 质量） | **100%**（确定性生成） | **100%**（指标走 MetricFlow） |
| **探索性查询支持** | **支持** | 不支持（只能查预定义指标） | **支持**（降级到 LLM） |
| **业务口径一致性** | 差（可能生成错误聚合逻辑） | **优**（YAML 统一定义） | **优**（指标有唯一口径） |
| **新指标扩展成本** | 无（LLM 即兴发挥） | 需写 YAML 定义 | 需写 YAML（但这是正确做法） |
| **复杂多表 Join** | 容易出错 | **MetricFlow 自动处理** | **MetricFlow 自动处理** |
| **时间维度分析** | 需 Prompt 工程 | **MetricFlow 原生支持** | **MetricFlow 原生支持** |
| **架构复杂度** | 低 | 中 | 中高 |
| **dbt 生态深度** | 浅（只用 manifest） | **深**（Semantic Layer 全套） | **深** |
| **Portfolio 含金量** | 中（常规 RAG 项目） | 中（偏工具使用） | **高**（架构决策能力体现） |

### 2.3 关键洞察：为什么混合方案最优

在一个真实的 BI 场景中，用户问题可以自然分为三类：

| 问题类型 | 占比（估算） | 示例 | 最佳处理路径 |
|----------|:----------:|------|-------------|
| **指标查询** | ~60% | "上月营收多少？" "客单价趋势？" | MetricFlow — 确定性生成，零幻觉 |
| **探索性查询** | ~30% | "购买超过3次的用户还买了什么？" | Text-to-SQL — 灵活，无预定义指标 |
| **元数据问答** | ~10% | "订单表有哪些字段？" "revenue 怎么算的？" | 直接检索 dbt docs，无需生成 SQL |

**结论**：纯 Text-to-SQL 在 60% 的高频场景（指标查询）中存在幻觉风险，这在 BI 场景中不可接受（"口径不对"是 BI 的原罪）。纯 MetricFlow 则无法覆盖 30% 的探索性需求。混合方案恰好取长补短。

### 2.4 MetricFlow 核心能力

MetricFlow（dbt Labs 开源的语义层引擎）提供：

```
输入: "按月查询 2024 年北美地区营收"
       ↓
MetricFlow 自动处理:
  ✓ 指标聚合逻辑 (SUM, COUNT DISTINCT, ratio...)
  ✓ 时间维度聚合 (按月 truncate + group by)
  ✓ 维度过滤 (region = 'North America')
  ✓ 多表 Join (orders → customers → regions)
  ✓ 指标间计算 (profit / revenue = margin%)
       ↓
输出: 100% 正确的 PostgreSQL SQL
```

这是 Text-to-SQL 无法保证的——LLM 可能在 Join 路径、聚合层级、过滤条件上犯错。

---

## 三、系统架构（基于混合方案）

### 3.1 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                      前端 (Chat UI)                          │
│                   Streamlit / Next.js                        │
│     ┌────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│     │ 对话面板    │  │ 数据表格      │  │ ECharts 图表     │   │
│     └─────┬──────┘  └──────┬───────┘  └────────┬─────────┘   │
└───────────┼────────────────┼───────────────────┼─────────────┘
            │                │                   │
            └────────────────┼───────────────────┘
                             │ SSE (流式响应)
┌────────────────────────────┴─────────────────────────────────┐
│                    后端 API 层 (FastAPI)                      │
│  ┌───────────┐  ┌───────────────┐  ┌──────────────────────┐  │
│  │ Chat API  │  │ Query Service │  │ Metadata Service     │  │
│  │ (SSE流式) │  │ (统一查询入口) │  │ (dbt manifest 解析)   │  │
│  └─────┬─────┘  └───────┬───────┘  └──────────┬───────────┘  │
└────────┼────────────────┼─────────────────────┼──────────────┘
         │                │                     │
┌────────┴────────────────┴─────────────────────┴──────────────┐
│                    AI Agent 核心层                            │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              ① 意图分类器 (Intent Router)             │    │
│  │      基于 LLM 语义理解，将问题路由到三条路径之一       │    │
│  └──────┬───────────────┬───────────────┬───────────────┘    │
│         │               │               │                    │
│         ▼               ▼               ▼                    │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │ Path A       │ │ Path B       │ │ Path C       │         │
│  │ 指标查询     │ │ 探索性查询   │ │ 元数据问答   │         │
│  │ (MetricFlow) │ │ (Text-to-SQL)│ │ (dbt Docs)   │         │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘         │
│         │                │                │                  │
│         ▼                ▼                ▼                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│  │ MetricFlow   │ │ SQL          │ │ RAG          │         │
│  │ Query API    │ │ Generator    │ │ Retriever    │         │
│  │ (确定性SQL)  │ │ (LLM + dbt   │ │ (向量检索    │         │
│  │              │ │  Context)    │ │  dbt docs)   │         │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘         │
│         │                │                │                  │
│         └────────────────┼────────────────┘                  │
│                          ▼                                   │
│               ┌──────────────────┐                           │
│               │  SQL 安全校验     │                           │
│               │  (只读/关键词/超时)│                           │
│               └────────┬─────────┘                           │
│                        ▼                                     │
│               ┌──────────────────┐                           │
│               │  SQL 执行器       │                           │
│               │  (PostgreSQL)     │                           │
│               └────────┬─────────┘                           │
│                        ▼                                     │
│               ┌──────────────────┐                           │
│               │  结果解读 +      │                           │
│               │  图表推荐 (LLM)  │                           │
│               └──────────────────┘                           │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 三条处理路径详解

#### Path A — 指标查询（MetricFlow，确定性路径）

```
用户: "上个月每个品类的销售额和订单数是多少？"

① 意图分类器 → 识别为"指标查询"，提取:
   - 指标: [revenue, order_count]
   - 维度: [product_category]
   - 时间: [last_month]
   - 过滤: 无

② MetricFlow Query Builder:
   构建 MF 查询:
   mf_query(
     metrics=["revenue", "order_count"],
     group_by=["product_category__category_name"],
     time_range=TimeRange("last_month")
   )

③ MetricFlow → 生成 SQL (100% 正确):
   SELECT
     pc.category_name,
     SUM(fo.order_amount) AS revenue,
     COUNT(DISTINCT fo.order_id) AS order_count
   FROM analytics.fact_orders fo
   LEFT JOIN analytics.dim_products p ON fo.product_id = p.product_id
   LEFT JOIN analytics.dim_product_categories pc ON p.category_id = pc.category_id
   WHERE fo.order_date >= '2026-04-01' AND fo.order_date < '2026-05-01'
   GROUP BY pc.category_name
```

#### Path B — 探索性查询（LLM Text-to-SQL，灵活路径）

```
用户: "过去一年中，购买超过3次的客户还同时购买了哪些品类？"

① 意图分类器 → 未匹配到预定义指标 → 降级到 Text-to-SQL

② RAG 检索相关 dbt 模型 (fact_orders, dim_customers, dim_products)

③ LLM 生成 SQL (带 dbt 上下文 + Few-shot)

④ 安全校验 → 执行 → 返回结果
```

#### Path C — 元数据问答（免查询路径）

```
用户: "revenue 指标是怎么计算的？包含退货吗？"

① 意图分类器 → 识别为"元数据问题"

② RAG 检索: dbt model descriptions, metric definitions, column docs

③ LLM 基于检索结果直接回答，不生成 SQL
```

### 3.3 技术栈（更新后）

| 层级 | 技术选型 | 选型理由 |
|------|----------|----------|
| **前端** | Streamlit | 快速原型；后期按需迁移 React |
| **后端** | FastAPI (Python) + SSE | 异步支持、流式响应、文档自动生成 |
| **LLM** | OpenAI API / Claude API | 意图分类 + 探索性 SQL 生成 + 结果解读 |
| **语义层引擎** | **dbt-core + MetricFlow** | **核心差异化组件：确定性 SQL 生成** |
| **数据库** | PostgreSQL 15+ | dbt 原生适配、分析型查询 |
| **向量存储** | ChromaDB | 轻量 RAG，存储 dbt docs + Few-shot 示例 |
| **DB 驱动** | SQLAlchemy 2.0 + asyncpg | 异步 + 连接池 |
| **图表** | ECharts (Pyecharts) | 图表类型丰富 |
| **编排** | 自研轻量 Agent | 避免 LangChain 过度抽象 |

---

## 四、功能规划

### 4.1 MVP 功能（v0.1.0 — 5 周）

| 模块 | 功能 | 优先级 | 路径 |
|------|------|--------|------|
| **意图分类** | 自动区分指标查询 / 探索查询 / 元数据问题 | P0 | 共用 |
| **指标查询** | 基于 MetricFlow 的确定性指标查询（Path A） | P0 | A |
| **探索查询** | 基于 LLM + dbt 上下文的即席 SQL 生成（Path B） | P0 | B |
| **元数据问答** | 基于 dbt docs 的直接回答（Path C） | P0 | C |
| **dbt 语义模型** | 定义 5-8 个核心指标 + 维度（semantic_models.yml） | P0 | A |
| **多轮对话** | 上下文保持、澄清反问 | P0 | 共用 |
| **可视化** | 自动推荐图表（柱状图/折线图/饼图）并渲染 | P0 | 共用 |
| **安全层** | SQL 只读校验、关键词过滤、超时限制 | P0 | 共用 |
| **示例数据** | E-commerce 数据集 + dbt 项目 | P0 | — |

### 4.2 V1 功能（v0.2.0）

| 模块 | 功能 | 优先级 |
|------|------|--------|
| 指标扩展 | 定义 15+ 业务指标、衍生指标（ratio 类） | P1 |
| 对话历史 | 持久化存储、可检索历史查询 | P1 |
| 查询优化 | SQL 执行计划分析 + 索引建议 | P1 |
| 导出 | CSV / Excel 导出 | P2 |
| Dashboard | 对话图表固定为 Dashboard | P2 |

---

## 五、实施步骤

### 第一阶段：环境与 dbt 语义层（第 1 周）

**目标**：搭建 PostgreSQL + dbt 项目 + 语义模型定义

| # | 任务 | 预估 |
|---|------|------|
| 1.1 | 项目骨架：Python 项目、虚拟环境、Git 仓库、目录结构 | 0.5 天 |
| 1.2 | Docker PostgreSQL、导入 E-commerce 示例数据（orders/customers/products） | 0.5 天 |
| 1.3 | dbt 项目：staging 模型、marts 宽表（事实表 + 维度表） | 1.5 天 |
| 1.4 | **dbt 语义层**：编写 `semantic_models.yml`，定义实体、维度、度量 | 1.5 天 |
| 1.5 | **MetricFlow 配置**：`metrics.yml`，定义 5-8 个核心指标（revenue, order_count, avg_order_value, customer_count...） | 1 天 |

**交付物**：dbt 项目 + 语义层 YAML + MetricFlow 可本地生成 SQL + PostgreSQL 含数据

### 第二阶段：后端核心（第 2-3 周）

**目标**：完成三种查询路径及其编排

#### 第 2 周：基础设施 + Path A（MetricFlow 路径）

| # | 任务 | 预估 |
|---|------|------|
| 2.1 | FastAPI 骨架：路由、配置、日志、SSE 支持 | 1 天 |
| 2.2 | Metadata Service：dbt manifest 解析 → 模型/列/关系/指标元数据 | 1 天 |
| 2.3 | **MetricFlow 集成**：Python 调用 MetricFlow query API，生成并获取 SQL | 2 天 |
| 2.4 | MetricFlow Query Builder：将 LLM 提取的参数构建为 MF 查询 | 1.5 天 |
| 2.5 | SQL Executor：SQLAlchemy 只读连接、安全校验、结果处理 | 1 天 |

#### 第 3 周：Path B + Path C + 编排

| # | 任务 | 预估 |
|---|------|------|
| 3.1 | **意图分类器**：LLM 驱动的三路意图路由（Prompt 工程核心） | 1.5 天 |
| 3.2 | RAG 模块：ChromaDB 初始化、dbt docs 向量化、检索接口 | 1.5 天 |
| 3.3 | SQL Generator（Path B）：LLM + dbt 上下文 + Few-shot 的 Text-to-SQL | 1.5 天 |
| 3.4 | 元数据问答（Path C）：RAG 检索 + LLM 直接回答 | 0.5 天 |
| 3.5 | Result Interpreter：查询结果 → 自然语言摘要 + 图表类型推荐 | 0.5 天 |
| 3.6 | Chat API 串联：三路编排 + 多轮对话 + SSE 流式响应 | 1.5 天 |

**交付物**：完整 Chat API，三条路径均可工作

### 第三阶段：前端开发（第 4 周）

**目标**：Chat UI + 表格 + 图表

| # | 任务 | 预估 |
|---|------|------|
| 4.1 | Streamlit 项目 + 布局设计 | 1 天 |
| 4.2 | 对话组件：消息列表、输入框、Markdown + SQL 代码块渲染 | 1.5 天 |
| 4.3 | SSE 流式接收：后端流式输出 → 前端逐字渲染 | 1 天 |
| 4.4 | 数据表格：结果表格、排序、分页 | 0.5 天 |
| 4.5 | 图表：ECharts 集成（柱状/折线/饼图）、自适应 | 1 天 |
| 4.6 | 辅助功能：SQL 展示/复制、追问建议 | 0.5 天 |

**交付物**：可交互的 Web 界面

### 第四阶段：测试、文档、发布（第 5 周）

**目标**：质量保证 + 开源发布

| # | 任务 | 预估 |
|---|------|------|
| 5.1 | 集成测试：端到端测试 20+ 个预设问题，覆盖三条路径 | 2 天 |
| 5.2 | MetricFlow 准确率验证：指标查询 100% 正确 | 0.5 天 |
| 5.3 | Bug 修复 | 1 天 |
| 5.4 | README + 架构文档 + 快速开始指南 | 1.5 天 |
| 5.5 | Docker 化：docker-compose 一键启动 | 1 天 |
| 5.6 | GitHub 发布 + Demo 录制 | 0.5 天 |

**交付物**：GitHub Release v0.1.0

---

## 六、目录结构（更新后）

```
data-agent-chatbi/
├── README.md
├── LICENSE                        # MIT
├── docker-compose.yml
├── .env.example
├── requirements.txt
│
├── dbt_project/                   # dbt 项目（含语义层）
│   ├── dbt_project.yml
│   ├── packages.yml
│   ├── models/
│   │   ├── staging/
│   │   │   ├── stg_orders.sql
│   │   │   ├── stg_customers.sql
│   │   │   ├── stg_products.sql
│   │   │   └── _stg__models.yml   # staging 层文档
│   │   └── marts/
│   │       ├── fact_orders.sql
│   │       ├── dim_customers.sql
│   │       ├── dim_products.sql
│   │       ├── _marts__models.yml
│   │       ├── semantic_models.yml   # ★ 语义模型定义
│   │       └── metrics.yml           # ★ MetricFlow 指标定义
│   ├── seeds/
│   │   ├── raw_orders.csv
│   │   ├── raw_customers.csv
│   │   └── raw_products.csv
│   └── macros/
│
├── backend/
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── chat.py                # Chat API (SSE)
│   │   └── health.py
│   ├── agent/
│   │   ├── orchestrator.py        # ★ 三路编排器
│   │   ├── intent_router.py       # ★ 意图分类器 (LLM)
│   │   ├── path_metric_query.py   # ★ Path A: MetricFlow 查询
│   │   ├── path_text_to_sql.py    # Path B: LLM SQL 生成
│   │   └── path_metadata_qa.py    # Path C: 元数据问答
│   ├── semantic/
│   │   ├── metricflow_engine.py   # ★ MetricFlow Python API 封装
│   │   ├── query_builder.py       # MetricFlow 查询构建器
│   │   └── dbt_manifest.py        # Manifest 解析
│   ├── rag/
│   │   ├── vector_store.py        # ChromaDB
│   │   ├── dbt_docs_loader.py     # dbt docs 向量化
│   │   └── retriever.py           # 检索接口
│   ├── sql/
│   │   ├── executor.py            # SQL 执行器
│   │   └── validator.py           # SQL 安全校验
│   ├── schemas/
│   │   ├── chat.py
│   │   └── query.py
│   └── llm/
│       ├── client.py              # LLM API 客户端 (OpenAI/Claude)
│       └── prompts.py             # 所有 Prompt 模板
│
├── frontend/
│   ├── app.py                     # Streamlit 入口
│   ├── components/
│   │   ├── chat.py
│   │   ├── table.py
│   │   └── chart.py
│   └── utils/
│       └── api_client.py
│
├── tests/
│   ├── test_metricflow.py         # MetricFlow 集成测试
│   ├── test_intent_router.py
│   ├── test_text_to_sql.py
│   └── test_integration.py
│
├── scripts/
│   ├── init_db.sh
│   ├── seed_data.py
│   ├── build_rag_index.py
│   └── validate_semantic.py       # 语义模型验证脚本
│
└── docs/
    ├── architecture.md            # 混合架构详解
    ├── semantic_layer.md          # 语义层设计说明
    └── development.md
```

---

## 七、关键技术细节

### 7.1 意图分类器 Prompt

```
你是 ChatBI 系统的查询路由器。根据用户问题，将其分类为以下三类之一：

1. METRIC_QUERY: 问题涉及预定义的业务指标（revenue, orders, customers, 
   conversion_rate 等），可以通过 MetricFlow 查询回答。
2. EXPLORATORY: 问题涉及探索性分析、自定义条件组合，无法用现有指标直接回答，
   需要生成自定义 SQL。
3. METADATA: 问题询问数据模型定义、指标口径、字段含义等元数据信息。

## 可用指标列表
{从 metrics.yml 提取的指标名称和描述}

## 可用维度
{从 semantic_models.yml 提取的维度和实体}

用户问题: {user_question}

返回 JSON:
{
  "type": "METRIC_QUERY" | "EXPLORATORY" | "METADATA",
  "confidence": 0.0-1.0,
  "extracted": {
    "metrics": [...],     // METRIC_QUERY 时提取
    "dimensions": [...],  // METRIC_QUERY 时提取
    "time_range": "...",  // METRIC_QUERY 时提取
    "filters": [...]      // METRIC_QUERY 时提取
  },
  "reasoning": "..."
}
```

### 7.2 MetricFlow Python API 集成

```python
# metricflow_engine.py
from metricflow import MetricFlowEngine
from metricflow.sql_clients.postgres import PostgresSQLClient

class MetricFlowService:
    """封装 MetricFlow，提供指标查询接口"""
    
    def __init__(self, dbt_project_path: str, profiles_dir: str):
        self.mf = MetricFlowEngine(
            sql_client=PostgresSQLClient(...),
            dbt_project_path=dbt_project_path,
            profiles_dir=profiles_dir,
        )
    
    def query_metrics(
        self,
        metrics: list[str],
        group_by: list[str] | None = None,
        time_range: str | None = None,
        where: list[str] | None = None,
    ) -> tuple[str, pd.DataFrame]:
        """
        通过 MetricFlow 查询指标。
        返回: (生成的SQL, 查询结果DataFrame)
        """
        mf_query = self.mf.build_query(
            metric_names=metrics,
            group_by=group_by or [],
            time_range=time_range,
            where=where or [],
        )
        sql = mf_query.sql
        result = self.mf.execute(mf_query)
        return sql, result
```

### 7.3 dbt 语义模型示例

```yaml
# dbt_project/models/marts/semantic_models.yml
semantic_models:
  - name: orders
    description: "订单事实数据"
    model: ref('fact_orders')
    defaults:
      agg_time_dimension: order_date
    entities:
      - name: order
        type: primary
        expr: order_id
      - name: customer
        type: foreign
        expr: customer_id
      - name: product
        type: foreign
        expr: product_id
    dimensions:
      - name: order_date
        type: time
        type_params:
          time_granularity: day
      - name: order_status
        type: categorical
        expr: status
      - name: is_returned
        type: categorical
    measures:
      - name: revenue
        description: "订单金额（已扣除退货）"
        agg: sum
        expr: net_amount
      - name: order_count
        description: "订单数"
        agg: count_distinct
        expr: order_id
      - name: avg_order_value
        description: "客单价"
        agg: average
        expr: net_amount
```

```yaml
# dbt_project/models/marts/metrics.yml
metrics:
  - name: total_revenue
    description: "总营收"
    label: "营收"
    type: simple
    type_params:
      measure: revenue
      
  - name: order_count
    description: "总订单数"
    label: "订单数"
    type: simple
    type_params:
      measure: order_count
      
  - name: daily_revenue
    description: "日营收趋势"
    label: "日营收"
    type: simple
    type_params:
      measure: revenue
    time_granularity: day
```

### 7.4 安全策略

```python
FORBIDDEN_KEYWORDS = [
    'INSERT', 'UPDATE', 'DELETE', 'DROP', 'TRUNCATE',
    'ALTER', 'CREATE', 'REPLACE', 'GRANT', 'REVOKE',
    'EXECUTE', 'EXEC', 'CALL',
]

# Path A (MetricFlow): 安全由 MetricFlow 保证，但仍做二次校验
# Path B (Text-to-SQL): 严格校验，禁止一切写操作

MAX_QUERY_TIMEOUT = 30          # 秒
MAX_RESULT_ROWS = 1000          # 行
READONLY_CONNECTION = True      # 只读事务
```

---

## 八、成功标准（更新后）

| # | 标准 | 衡量方式 |
|---|------|----------|
| 1 | **三条路径均可用** | 指标查询 / 探索查询 / 元数据问答各测试 10 个问题 |
| 2 | **Path A 准确率 = 100%** | MetricFlow 路径的指标查询 SQL 语义完全正确 |
| 3 | **Path B 准确率 ≥ 70%** | Text-to-SQL 路径 SQL 语法正确 + 语义基本符合预期 |
| 4 | **一键启动** | `docker-compose up` 启动完整系统 |
| 5 | **README 完善** | 新用户 10 分钟内启动并运行第一个查询 |
| 6 | **语义层可扩展** | 添加新指标只需修改 YAML，无需改代码 |

---

## 九、风险评估

| 风险 | 概率 | 影响 | 应对 |
|------|:----:|:----:|------|
| MetricFlow API 兼容性问题 | 低 | 高 | 固定 dbt-core + MetricFlow 版本；Docker 化确保环境一致 |
| 意图分类器误判问题类型 | 中 | 中 | 低置信度时反问用户确认；支持手动切换查询路径 |
| LLM 生成 SQL 准确率低 | 中 | 中 | Path A 承担 60% 查询量，Path B 作为补充；提供 SQL 可编辑入口 |
| MetricFlow 学习曲线 | 中 | 低 | 已规划 1.5 天学习 + 配置时间，有官方文档支持 |
| 复杂查询性能差 | 低 | 中 | 超时限制 + dbt 物化视图 + 索引优化 |

---

## 十、时间规划

```
Week 1  ████████ 环境 + dbt 建模 + MetricFlow 语义层定义
Week 2  ████████ Path A (MetricFlow) + SQL 执行 + 安全层
Week 3  ████████ Path B/C (Text-to-SQL + Metadata QA) + 意图路由 + 编排
Week 4  ████████ 前端 (Streamlit Chat UI + ECharts 图表)
Week 5  ████████ 集成测试 + 文档 + Docker + GitHub 发布
────────────────────────────────────────────────────
         MVP v0.1.0 上线
```

总工期：**5 周**（比纯 Text-to-SQL 方案多 1 周，用于 MetricFlow 语义层定义和集成）

---

## 十一、总结

经过对三种方案的系统评估，**混合方案（MetricFlow + Text-to-SQL）**在可行性、准确率、灵活性和 Portfolio 含金量四个维度上均为最优解：

- **不是为了"用 dbt"而用 dbt**——MetricFlow 解决了 Text-to-SQL 最核心的准确率问题
- **架构决策有依据**——三类问题三条路径，各自用最适合的技术
- **面试可深度讨论**——从"为什么不用 LangChain"到"MetricFlow 和直接 Text-to-SQL 的 trade-off"都能展开
- **技术栈聚焦**——dbt 生态深耕而非泛泛的全栈

需要我开始实施吗？建议从第一阶段开始：创建项目骨架 + dbt 语义层。
