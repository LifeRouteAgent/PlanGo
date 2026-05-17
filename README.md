# LifeRouteAgent

LifeRouteAgent 是一个面向本地生活出行决策的多 Agent 路线规划系统。项目目标是把用户的一句自然语言需求，例如“周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元”，拆解成可执行的本地生活计划：理解意图、抽取约束、召回 POI、并行推荐餐饮/活动/休闲服务、规划时间路线、校验可行性、生成最终方案，并预留后续预订执行入口。

当前版本是 Hackathon 原型到工程化项目的迁移版本。后端采用 Python + FastAPI + LangGraph，前端采用 Vue + TypeScript + Vite，POI 数据优先支持本地 MySQL 自建库，也保留 Mock 模式用于无数据库环境下演示 DAG 流程。

## 核心能力

- 自然语言需求解析：识别人数、时间、预算、偏好、出行场景等约束。
- 多源 POI 召回：支持景点、购物、Klook 活动、餐饮、健身、休闲娱乐、美容养生等自建表。
- 多 Agent 编排：通过 LangGraph DAG 串联解析、约束构建、候选召回、并行推荐、路线规划、校验、排序和执行。
- 本地生活分表存储：不同业务域独立建表，方便后续让不同 Agent 使用不同召回策略。
- 数据库/Mock 双模式：`LIFEROUTE_USE_DATABASE=1` 时读取 MySQL；否则使用内置 Mock 数据。
- 可扩展履约入口：保留可用性检查、用户确认和执行 Agent，后续可接入订座、购票、下单、退款等真实接口。

## Agent 架构

当前 LangGraph DAG 位于 `backend/app/dag/langgraph_dag_config.py`。

```text
START
  -> Intent Parser
  -> Constraint Builder
  -> Planner Agent
  -> POI Collector
      -> POI Mix Recommend
      -> POI Activity Recommend
      -> POI Restaurant Recommend
      -> POI Lifestyle Recommend
  -> Route & Time Planner
  -> Availability Checker
  -> Verifier
      -> Ranker
      -> Planner Agent       # 需要重规划时回退
      -> Response Generator  # 无法满足时直接响应
  -> Response Generator
  -> User Confirm
  -> Execution Agent
END
```

各节点职责：

- `Intent Parser`：把用户自然语言转成结构化意图。
- `Constraint Builder`：归一化时间、人数、预算、距离、偏好和硬约束。
- `Planner Agent`：根据意图决定需要哪些 POI 类别与推荐路径。
- `POI Collector`：从 MySQL 或 Mock 数据中按类别召回候选 POI。
- `POI Mix Recommend`：处理跨类型组合推荐，例如吃饭 + 电影 + 商场。
- `POI Activity Recommend`：推荐 Klook 活动、体验项目和可预约活动。
- `POI Restaurant Recommend`：推荐餐饮 POI。
- `POI Lifestyle Recommend`：推荐健身、娱乐、美容养生等生活服务。
- `Route & Time Planner`：把候选点位组合成时间顺序和路线结构。
- `Availability Checker`：校验营业时间、可用性和基础风险。
- `Verifier`：判断方案是否满足约束，不满足则回退重规划。
- `Ranker`：对可行方案进行排序。
- `Response Generator`：生成面向用户的最终解释。
- `User Confirm`：预留用户确认节点。
- `Execution Agent`：预留真实履约执行节点。

## 系统架构

```text
Frontend (Vue + Vite)
  -> FastAPI REST API
    -> LangGraph DAG
      -> Agent Nodes
      -> Recommendation Skills
      -> POI Repository
        -> MySQL life_route_agent
          -> poi_attractions
          -> poi_shoppings
          -> poi_activities
          -> poi_restaurant
          -> poi_fitness
          -> poi_entertainment
          -> poi_beauty
```

分层说明：

- `frontend`：用户输入、方案展示、执行状态和导出入口。
- `backend/app/api`：FastAPI 路由层，提供 `/health`、`/trip/plan`、导出接口。
- `backend/app/dag`：LangGraph DAG 配置。
- `backend/app/agents`：核心 Agent 节点。
- `backend/app/tools`：推荐 Skill 和统一 POI schema。
- `backend/app/services`：数据库仓储、餐厅/活动/生活服务业务服务、导出服务。
- `backend/app/state`：DAG 中流转的 `PlanState`。
- `backend/app/models`：API Schema 和数据库模型定义。
- `database/sql`：本地 POI 自建库 DDL + INSERT SQL。

## POI 数据库设计

项目采用“业务域分表 + Collector 统一出口”的设计。分表便于不同 Agent 独立优化召回逻辑，Collector 层再把不同表字段规范化为统一 `PoiRecord`。

已支持的 POI 表：

| 表名 | 数据来源 | 用途 |
| --- | --- | --- |
| `poi_attractions` | 景点 TSV | 景点、城市游玩、观光 |
| `poi_shoppings` | 购物 TSV | 商场、购物中心、生活广场 |
| `poi_activities` | Klook 活动 TSV | 活动、体验、一日游、票券 |
| `poi_restaurant` | 高德 POI | 餐厅美食 |
| `poi_fitness` | 高德 POI | 健身房、瑜伽、普拉提、运动场馆 |
| `poi_entertainment` | 高德 POI | KTV、棋牌室、电影院 |
| `poi_beauty` | 高德 POI | 按摩、足疗、洗浴、美容美发 |

高德类表保留了 `raw JSON`，同时清洗出 `rating`、`cost`、`open_time`、`photos`、`head_image`、`typecode`、`keytag` 等高频使用字段。

## 项目代码结构

```text
LifeRouteAgent/
  backend/
    app/
      agents/              # LangGraph 节点实现
      api/                 # FastAPI 应用和路由
      dag/                 # LangGraph DAG 配置
      models/              # API 与数据库模型
      services/            # POI 仓储、业务服务、导出服务
      state/               # PlanState 定义
      tools/               # 推荐 Skill、POI schema
      config.py            # 环境变量配置
    tests/                 # 后端测试
    requirements.txt       # Python 依赖
    .env.example           # 后端环境变量模板
  frontend/
    src/                   # Vue 前端源码
    package.json           # 前端依赖和脚本
    vite.config.ts         # Vite 配置
  database/
    sql/                   # 本地 POI 建表和导入 SQL
  assets/                  # 项目静态资产
  README.md
  CHANGELOG.md
```

## 环境要求

推荐环境：

- Python 3.11+
- Node.js 18+
- MySQL 8.0+
- Windows PowerShell / macOS shell / Linux shell 均可

后端依赖见 `backend/requirements.txt`：

```text
fastapi
uvicorn[standard]
langgraph
pydantic
python-dotenv
httpx
pytest
pymysql
```

前端依赖见 `frontend/package.json`：Vue、TypeScript、Vite。

## 环境变量

复制后端环境变量模板：

```powershell
Copy-Item backend\.env.example backend\.env
```

主要配置：

```text
MIMO_API_KEY=                 # MiMo LLM Key，可为空，按当前实现降级使用规则/Mock
MIMO_BASE_URL=https://api.xiaomimimo.com/v1
MIMO_MODEL=mimo-v2.5-pro
AMAP_API_KEY=                 # 高德 API Key，数据采集脚本使用
APP_ENV=local
LIFEROUTE_USE_DATABASE=0      # 0 使用 Mock；1 使用 MySQL 自建 POI 库
DATABASE_HOST=127.0.0.1
DATABASE_PORT=3306
DATABASE_USER=root
DATABASE_PASSWORD=
DATABASE_NAME=life_route_agent
```

## 初始化数据库

创建数据库：

```powershell
mysql --default-character-set=utf8mb4 -h localhost -uroot -p -e "CREATE DATABASE IF NOT EXISTS life_route_agent DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;"
```

导入全部 POI SQL：

```powershell
mysql --default-character-set=utf8mb4 -h localhost -uroot -p life_route_agent < database\sql\poi_attractions.sql
mysql --default-character-set=utf8mb4 -h localhost -uroot -p life_route_agent < database\sql\poi_shoppings.sql
mysql --default-character-set=utf8mb4 -h localhost -uroot -p life_route_agent < database\sql\poi_activities.sql
mysql --default-character-set=utf8mb4 -h localhost -uroot -p life_route_agent < database\sql\poi_restaurant.sql
mysql --default-character-set=utf8mb4 -h localhost -uroot -p life_route_agent < database\sql\poi_fitness.sql
mysql --default-character-set=utf8mb4 -h localhost -uroot -p life_route_agent < database\sql\poi_entertainment.sql
mysql --default-character-set=utf8mb4 -h localhost -uroot -p life_route_agent < database\sql\poi_beauty.sql
```

开启数据库模式：

```text
LIFEROUTE_USE_DATABASE=1
DATABASE_NAME=life_route_agent
```

当前导入数据量：

| 表名 | 行数 |
| --- | ---: |
| `poi_attractions` | 3457 |
| `poi_shoppings` | 1960 |
| `poi_activities` | 297 |
| `poi_restaurant` | 21327 |
| `poi_fitness` | 4147 |
| `poi_entertainment` | 1869 |
| `poi_beauty` | 20267 |

## 启动后端

进入后端目录：

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

启动 API：

```powershell
uvicorn app.api.main:app --reload --host 127.0.0.1 --port 8000
```

健康检查：

```powershell
curl http://127.0.0.1:8000/health
```

调用规划接口：

```powershell
curl -X POST http://127.0.0.1:8000/trip/plan `
  -H "Content-Type: application/json" `
  -d '{"user_query":"周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元"}'
```

也可以直接运行一次 DAG：

```powershell
python -m app.api.main
```

## 启动前端

```powershell
cd frontend
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173/
```

构建前端：

```powershell
npm run build
```

## 验证和指标

后端测试：

```powershell
cd backend
pytest
```

前端类型检查：

```powershell
cd frontend
npm run typecheck
```

前端构建：

```powershell
cd frontend
npm run build
```

运行期建议关注的指标：

- DAG 总耗时：一次 `/trip/plan` 从请求到响应的耗时。
- 节点耗时：Intent、Collector、Recommend、Route、Verifier、Ranker 各节点耗时。
- Collector 召回量：各 POI 类别候选数量。
- Verifier 通过率：方案一次通过、回退重规划、失败响应的比例。
- 数据库查询耗时：按类别查询 MySQL 的耗时和慢查询。
- 推荐命中率：用户最终确认的方案与推荐排序位置。
- 履约成功率：后续接入真实订座/购票/下单后的执行成功率。

## 当前边界

- POI 数据已支持本地 MySQL 自建库。
- 真实预订、排队、库存和支付还未接入，当前执行 Agent 是可扩展入口。
- 高德数据以已采集 SQL 形式提交，后续如需刷新数据，应重新运行采集和清洗脚本后替换 `database/sql`。
- 真实 Agent 质量取决于 LLM Key、POI 完整度、营业状态校验和路线耗时服务，当前项目重点是工程骨架和数据闭环。
