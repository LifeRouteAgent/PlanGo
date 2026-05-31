# LifeRouteAgent

LifeRouteAgent 是一个面向本地生活周末活动的 Agentic Planning 项目。它不是简单的 POI 搜索或聊天机器人，而是通过 **FastAPI + LangGraph + MySQL + React**，把自然语言需求拆解成可执行的本地生活方案：召回地点、推荐组合、规划路线、校验预算和时长、生成用户可读解释，并提供 mock 执行、Memory、Trace、PDF/ICS 导出和评测能力。

完整项目介绍、代码讲解、答辩稿和 Mermaid 图见：[docs/PROJECT_INTRODUCTION.md](docs/PROJECT_INTRODUCTION.md)。

## 当前能力

- 自然语言理解：区分简单问答、单类推荐和完整规划。
- LangGraph DAG：Intent、Constraint、Planner、Collector、并行 Skill、Route Planner、Verifier、LLM Critic、Ranker、Response。
- 七类 POI：景点、购物、活动、餐厅、健身、娱乐、美容养生。
- 本地 MySQL 数据源：`database/sql` 提供 POI 表 SQL。
- 多 Skill 推荐：活动、餐厅、生活娱乐、景点/商场混合推荐。
- 路线与时间线：生成 `timeline`、`route_segments`、预算和总时长。
- 高德增强：路线和天气接口已接入，失败回退 Haversine/默认天气。
- 流式输出：后端 SSE 推送节点进度、文本片段和最终方案。
- 执行入口：预约、购票、打车为 mock；日历 ICS 和中文 Markdown PDF 导出已实现。
- Memory：文件画像 + 会话记忆 + Milvus 向量记忆接口。
- 运行治理：ToolHarness、ToolPolicy、Checkpoint、RuntimeStore、TraceRecorder、Node Metrics。
- Prompt 治理：Prompt 文本放在 `backend/app/prompts`，并由 `PromptRegistry` 记录版本。
- 评测：后端测试覆盖 intent、planner、route、verifier、memory、runtime、eval 等模块。

## 技术栈

后端：

- Python
- FastAPI
- LangGraph
- Pydantic
- PyMySQL
- HTTPX
- Milvus / sentence-transformers
- ReportLab

前端：

- React
- TypeScript
- Vite
- lucide-react
- 原生 CSS

## 一键 Docker Compose

仓库提供完整 `docker-compose.yml`，包含：

- MySQL
- Milvus Standalone（etcd + minio + milvus）
- FastAPI 后端
- Vite 前端

出于安全原因，真实 LLM / 高德 / MySQL / MinIO 密钥不提交到 GitHub。请在本机环境或 `.env` 中设置：

```powershell
$env:MYSQL_ROOT_PASSWORD="your-local-password"
$env:MINIO_SECRET_KEY="your-minio-secret"
$env:DEEPSEEK_API_KEY="your-deepseek-key"
$env:AMAP_API_KEY="your-amap-key"
docker compose up --build
```

访问：

```text
后端：http://127.0.0.1:8000
前端：http://127.0.0.1:5173
```

如果只需要 Milvus，可继续使用：

```powershell
docker compose -f docker-compose.milvus.yml up -d
```

## 后端本地启动

```powershell
cd C:\Users\dengp\project\LifeRouteAgent
python -m venv .venv
.\.venv\Scripts\pip.exe install -r backend\requirements.txt

cd backend
..\.venv\Scripts\python.exe -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000
```

健康检查：

```text
GET http://127.0.0.1:8000/health
```

## 前端本地启动

```powershell
cd C:\Users\dengp\project\LifeRouteAgent\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

访问：

```text
http://127.0.0.1:5173
```

## 配置

后端配置从文件读取，入口是 `backend/app/config.py`。

读取优先级：

1. `LIFEROUTE_CONFIG_PATH` 指定的配置文件；
2. `backend/config.local.json`；
3. `backend/config.example.json`。

```powershell
Copy-Item backend\config.example.json backend\config.local.json
```

主要配置项：

```json
{
  "LLM_PROVIDER": "deepseek",
  "DEEPSEEK_API_KEY": "",
  "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
  "DEEPSEEK_MODEL": "deepseek-v4-pro",
  "AMAP_API_KEY": "",
  "AMAP_ROUTE_ENABLED": false,
  "LIFEROUTE_USE_DATABASE": true,
  "DATABASE_HOST": "127.0.0.1",
  "DATABASE_PORT": 3306,
  "DATABASE_USER": "root",
  "DATABASE_PASSWORD": "",
  "DATABASE_NAME": "life_route_agent",
  "MILVUS_ENABLED": true,
  "RUNTIME_STORE": "mysql",
  "RUNTIME_MYSQL_ENABLED": true
}
```

前端高德 JS 地图读取 `frontend/public/app-config.json`，该文件可以提交到仓库作为字段模板；真实 key 建议由本机或部署流程写入，不建议提交到 GitHub。

```json
{
  "amap_key": "",
  "amap_security_js_code": ""
}
```

后端也提供 `GET /trip/client-config` 作为兼容配置源；前端优先读取 `app-config.json`，失败后再读取后端接口。

## 数据库

POI 表 SQL：

```text
database/sql/
├── poi_activities.sql
├── poi_attractions.sql
├── poi_beauty.sql
├── poi_entertainment.sql
├── poi_fitness.sql
├── poi_restaurant.sql
└── poi_shoppings.sql
```

Runtime 表初始化：

```powershell
cd C:\Users\dengp\project\LifeRouteAgent\backend
..\.venv\Scripts\python.exe scripts\init_runtime_schema.py
```

会创建：

- `runtime_sessions`
- `runtime_tasks`
- `runtime_tool_cache`
- `runtime_trace_events`
- `runtime_node_metrics`

## PDF / Prompt / API 对齐

- PDF：`backend/app/services/markdown_pdf_service.py` 先把方案转换为 Markdown，再用 ReportLab 生成中文 PDF，包含概览表、时间线、地点详情和路线信息。
- Prompt：外置在 `backend/app/prompts`，`PromptRegistry` 维护 prompt/schema 版本。
- API 兼容：前端历史接口 `/api/plan-stream`、`/api/cities`、`/api/user/profile`、`/api/plans/{planId}/{action}` 已在 `compat.py` 中兼容。
- `backend/app/models/db_models.py` 已删除；当前项目使用 Pydantic schema + repository，不使用空 ORM 文件。

## 核心流程

```mermaid
flowchart TD
  A["用户输入"] --> B["SSE /trip/plan/stream"]
  B --> C["TripStreamingService"]
  C --> D["create_initial_state"]
  D --> E["LangGraph DAG"]
  E --> F["Intent Router / Parser"]
  F --> G["Constraint Builder / Clarifier"]
  G --> H["Planner Agent"]
  H --> I["POI Collector"]
  I --> J["并行推荐 Skills"]
  J --> K["Route & Time Planner"]
  K --> L["Availability Checker / Verifier"]
  L --> M["LLM Critic"]
  M --> N["Ranker"]
  N --> O["Response Generator"]
  O --> P["前端方案卡片 / 对话回复 / Trace 面板"]
```

## 重要目录

```text
backend/app/api/        FastAPI 路由
backend/app/agents/     LangGraph 节点
backend/app/dag/        DAG 配置
backend/app/prompts/    外置 Prompt 模板
backend/app/services/   LLM、Memory、Runtime、Trace、ToolHarness、POI 仓储
backend/app/tools/      推荐 Skill 与 POI schema
backend/app/state/      PlanState
backend/tests/          后端测试
frontend/src/api/       前端请求和 SSE 解析
frontend/src/hooks/     流式规划状态
frontend/src/pages/     页面
frontend/src/components/组件
database/sql/           POI 表 SQL
docs/                   项目介绍和答辩文档
```

## 主要 API

- `GET /health`
- `POST /trip/plan`
- `POST /trip/plan/stream`
- `POST /trip/plan/revise/stream`
- `POST /trip/plan/adjust`
- `POST /trip/execute/stream`
- `POST /trip/calendar/ics`
- `POST /export/plan/pdf`
- `GET /trip/trace/{trace_id}`
- `GET /trip/observability/node-metrics`
- `GET /trip/observability/runtime-health`
- `GET /trip/memory/profile`
- `GET /trip/memory/search`
- `GET /trip/data-source`
- `GET /api/cities`
- `GET /api/user/profile`
- `POST /api/plan-stream`
- `POST /api/plans/{planId}/{action}`

## 测试

后端：

```powershell
cd C:\Users\dengp\project\LifeRouteAgent\backend
..\.venv\Scripts\python.exe -m pytest tests -q
```

前端：

```powershell
cd C:\Users\dengp\project\LifeRouteAgent\frontend
npm run build
```
