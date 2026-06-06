# 项目目录说明

本文档描述当前 LifeRouteAgent 的目录职责。当前后端已按 V2 规划架构整理：`graph` 目录取消，编排统一进入 `planning`；通用“大杂烩” `services` 目录取消，按 repository、memory、runtime、integration 等边界拆分。

## 顶层目录

- `assets/`：项目静态素材和说明图片。
- `backend/`：FastAPI 后端、Planning Graph V2、数据库仓库、LLM agent、Memory、Trace 和导出能力。
- `database/`：数据库初始化、表结构和数据准备资源。
- `docs/`：项目设计、架构和维护文档。
- `frontend/`：前端应用，负责对话、方案卡片、地图路线和 POI 详情展示。
- `scripts/`：开发、数据处理或运维辅助脚本。
- `.vscode/`：本地 VS Code 工作区配置。
- `docker-compose.yml`：本地联调所需服务编排配置。
- `docker-compose.milvus.yml`：向量检索相关服务编排配置。
- `README.md`：项目入口说明。
- `CHANGELOG.md`：项目变更记录。

## 后端目录

- `backend/app/api/`：HTTP API、SSE 流式接口和兼容路由入口。
- `backend/app/api/schemas/`：对外请求、响应和接口契约模型。
- `backend/app/agents/`：具体 LLM 任务封装，例如意图理解、响应文案生成和记忆抽取。
- `backend/app/bus/`：内部事件总线和进度投影订阅器。
- `backend/app/compat/`：旧版本兼容类型和迁移边界。
- `backend/app/context/`：当前会话上下文、session 读写、指代和偏好上下文构建。
- `backend/app/core/`：通用配置、异常和跨模块追踪入口。
- `backend/app/domain/`：领域对象、枚举、POI 类型和业务常量。
- `backend/app/evaluation/`：本地评测和回归用例执行器。
- `backend/app/export/`：Markdown、PDF、ICS 等导出服务。
- `backend/app/integrations/`：外部服务适配，例如高德路线、天气、日历和 embedding。
- `backend/app/llm/`：底层 LLM provider、prompt 注册、结构化输出校验和调用追踪。
- `backend/app/memory/`：长期记忆、向量记忆、偏好抽取和异步记忆写入。
- `backend/app/observability/`：Trace 记录和用户可见进度投影。
- `backend/app/planning/`：Planning Graph V2 的编排、节点、状态、规划业务服务和前端 payload 契约。
- `backend/app/prompts/`：当前仍会被加载的 LLM prompt 模板。
- `backend/app/repositories/`：数据库访问层，只负责查询、映射和参数化 SQL。
- `backend/app/runtime/`：运行时目录、checkpoint、幂等键和持久化 runtime store。
- `backend/app/streaming/`：流式响应相关工具。
- `backend/app/tools/`：外部工具调用框架、风险策略和重试封装。
- `backend/config/`：运行时策略配置，例如规划阈值、类别策略和风险策略。
- `backend/tests/`：后端单元测试、契约测试和回归测试。

## Planning

- `backend/app/planning/graph_builder.py`：组装 Planning Graph V2 节点、分支和回退循环。
- `backend/app/planning/intent_rules.py`：无 LLM 的确定性意图和类别兜底规则。
- `backend/app/planning/payloads.py`：前端响应 payload 的结构校验和展示字段清洗。
- `backend/app/planning/poi_catalog_service.py`：POI 表字段、标签和背景知识目录服务。
- `backend/app/planning/policy_config.py`：规划、类别和风险策略配置加载。
- `backend/app/planning/scoring_service.py`：POI 候选打分逻辑。
- `backend/app/planning/trip_services.py`：Trip API 背后的应用服务入口，负责调用 V2 图和兼容响应。

## Planning State

- `backend/app/planning/state/base.py`：状态模型基类、请求类型、逻辑类别和物理表映射。
- `backend/app/planning/state/context.py`：用户、地理位置、会话、偏好和 POI 标签背景上下文。
- `backend/app/planning/state/understanding.py`：LLM 意图理解、slot、预算、距离、时间和默认值理解结果。
- `backend/app/planning/state/constraints.py`：硬约束、软偏好、距离、预算、时间、评分和 fallback 策略。
- `backend/app/planning/state/recall.py`：召回计划、物理查询、must POI 解析、候选和候选评分状态。
- `backend/app/planning/state/plans.py`：路线 slot、候选方案、可用性、校验、排序特征和最终方案结果。
- `backend/app/planning/state/response.py`：响应状态、debug trace、异步事件、PlanningState 和旧响应兼容转换器。
- `backend/app/planning/state/schemas.py`：稳定聚合导出入口，避免调用方依赖 state 内部拆分。
- `backend/app/planning/state/__init__.py`：状态包公开导出入口。

## Planning Nodes

- `candidate_nodes.py`：POI 候选评分和候选池平衡节点。
- `common.py`：节点通用 state 解析和 trace 追加工具。
- `constraint_nodes.py`：约束构建节点。
- `context_nodes.py`：请求上下文、会话和 Memory 读取节点。
- `intent_nodes.py`：意图理解、偏好抽取和异步事件投递节点。
- `planning_nodes.py`：方案编辑和路线组合节点。
- `recall_nodes.py`：召回计划编译和候选收集节点。
- `response_nodes.py`：结构化响应组装、LLM 文案生成和简单问答响应节点。
- `session_nodes.py`：会话状态保存节点。
- `validation_nodes.py`：预排序、可用性检查、失败分析、回退放宽和最终排序节点。

## Planning Services

- `intent_service.py`：融合 LLM 和规则输出，生成结构化意图、类别、slot 和必去 POI。
- `constraint_service.py`：合并用户约束、默认值、餐厅规则、时间、预算、距离和召回需求。
- `recall_service.py`：把逻辑召回计划编译为安全查询，并从 POI repository 收集候选。
- `candidate_service.py`：调用 POI scorer 并保留多样化候选池。
- `routing_service.py`：组合候选方案、计算路线指标、过滤重复和相邻过近 POI。
- `availability_service.py`：检查营业、预约、排队风险，并分析失败原因和放宽策略。
- `ranking_service.py`：计算方案排序特征并选出最终候选方案。
- `response_service.py`：把内部方案转换为前端安全 payload。
- `common.py`：规划服务共享常量、标签清洗、图片清洗和通用打分工具。

## LLM 与 Prompt

- `backend/app/agents/intent_agent.py`：调用 LLM 生成结构化意图理解结果。
- `backend/app/agents/response_agent.py`：调用 LLM 生成方案标题、优缺点、标签和最终回复。
- `backend/app/agents/memory_extractor_agent.py`：调用 LLM 抽取记忆、会话偏好和修订语义。
- `backend/app/llm/llm_client.py`：统一封装模型调用、JSON 提取、工具调用和 trace。
- `backend/app/llm/output_schemas.py`：LLM 结构化输出 schema 和校验器。
- `backend/app/llm/prompt_registry.py`：prompt 版本登记和模板加载。
- `backend/app/prompts/intent_understanding.md`：V2 意图理解 prompt。
- `backend/app/prompts/response_generation_package.md`：V2 响应标题、优缺点、标签和最终回复生成 prompt。
- `backend/app/prompts/memory_extractor.md`：异步 Memory 提取 prompt。
- `backend/app/prompts/revision_parser.md`：方案调整或修订语义解析 prompt。
- `backend/app/prompts/followup_context.md`：上下文合并和追问答案识别 prompt。

## 数据与运行时

- `backend/app/repositories/poi_repository.py`：MySQL POI 参数化查询、名称搜索、安全字段映射和 fallback。
- `backend/app/memory/memory_service.py`：用户长期记忆读取、写入和检索服务。
- `backend/app/memory/memory_store.py`：文件或 runtime store 的 Memory 持久化适配。
- `backend/app/memory/vector_memory_store.py`：向量记忆记录和检索存储。
- `backend/app/memory/memory_event_queue.py`：异步 Memory 写入队列。
- `backend/app/memory/session_preference_extractor.py`：当前会话偏好抽取。
- `backend/app/context/context_builder.py`：为 LLM 构造脱敏上下文。
- `backend/app/context/session_store.py`：会话状态保存和读取。
- `backend/app/runtime/runtime_paths.py`：运行时数据目录定义。
- `backend/app/runtime/runtime_store.py`：Session、Task、Trace、Tool cache 的持久化抽象。
- `backend/app/runtime/checkpoint_store.py`：长任务 checkpoint 和幂等键管理。

## 外部能力与工具

- `backend/app/integrations/amap_route_service.py`：高德路线查询和路线 fallback。
- `backend/app/integrations/amap_weather_service.py`：天气信息查询。
- `backend/app/integrations/calendar_service.py`：方案日历 ICS 生成。
- `backend/app/integrations/embedding_service.py`：文本向量生成服务。
- `backend/app/tools/tool_harness.py`：外部工具调用超时、重试、trace 和 fallback 包装。
- `backend/app/tools/tool_policy.py`：工具风险等级和确认策略。
- `backend/app/observability/trace_recorder.py`：规划 trace 和节点指标记录。
- `backend/app/observability/trip_progress.py`：SSE 进度和产品化事件投影。

## Frontend

- `frontend/src/api/`：前端 API 请求封装。
- `frontend/src/components/`：对话、方案卡片、地图、时间线和通用 UI 组件。
- `frontend/src/hooks/`：前端状态和副作用复用逻辑。
- `frontend/src/lib/`：前端工具库和共享配置。
- `frontend/src/pages/`：页面级组件。
- `frontend/src/styles/`：全局样式和页面样式。
- `frontend/src/types/`：前端 TypeScript 类型定义。
- `frontend/src/utils/`：前端格式化、转换和辅助函数。
