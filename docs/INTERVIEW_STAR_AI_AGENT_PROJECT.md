# LifeRouteAgent 高级 / 资深 AI Agent 岗位项目介绍（STAR 版）

> 适用场景：高级 / 资深 AI Agent 工程师面试、项目答辩、简历深挖、架构讲解。  
> 说明：本文基于当前 LifeRouteAgent 仓库代码整理。真实订座、购票、打车目前是 mock 执行；PDF、ICS、Trace、Memory、LangGraph DAG、MySQL POI、Milvus 接口、SSE 前端展示等能力已在项目中实现或接入。

## 1. 30 秒项目概述

LifeRouteAgent 是一个面向本地生活周末活动的 AI Agent 规划系统。它把用户一句自然语言需求，例如“明天和对象去环球影城，再去唱歌，两个人预算 1000”，转换成可执行的本地生活方案：先用 LLM 做意图和约束理解，再通过 LangGraph 编排 Planner、Collector、Skill、Route Planner、Verifier、Critic、Ranker 和 Response Generator，最后输出 3 个带地点、时间线、路线、预算、优缺点和执行入口的方案。

它的核心价值不是“聊天生成建议”，而是把本地生活决策从“搜索一堆地点”推进到“可验证、可调整、可恢复、可观测的执行型 Agent”。

## 2. STAR 项目讲解主线

### S：Situation 背景

本地生活场景里，用户通常不是单纯想查一个地点，而是要解决一个组合决策问题：

- 和谁去：情侣、朋友、家庭、亲子；
- 去哪里：景点、餐厅、KTV、棋牌、商场、按摩、展览；
- 怎么安排：先后顺序、停留时间、交通时间、预算控制；
- 能不能执行：营业、距离、排队、路线、天气、预约；
- 不满意怎么改：不要室外、换近一点、换便宜一点、不要某类餐厅。

普通 POI 搜索只能返回地点列表，普通 LLM 又容易只生成看似合理但不可落地的文本。业务上真正有价值的是：**把自然语言需求变成可执行方案，并能继续调整、分享、预约和追踪效果**。

所以这个项目的背景是：从“搜索推荐系统”升级到“本地生活可执行规划 Agent”，把 LLM、数据库、路线、记忆、工具治理和前端交互串成一个完整闭环。

### T：Task 目标

我给这个项目设定的目标不是做一个简单 demo，而是做一个具备生产化雏形的 Agent 系统：

1. **业务目标**
   - 降低用户做周末活动决策的成本；
   - 从地点推荐升级到完整方案规划；
   - 支持规划后的执行、调整、分享和导出；
   - 为后续接入真实履约 API，比如订座、购票、打车，预留清晰边界。

2. **Agent 目标**
   - 能区分简单问答、单类推荐和完整规划；
   - 能理解人数、预算、时间、偏好、必须地点、排除项；
   - 能用多 Agent / DAG 方式把任务拆成可观察的步骤；
   - 能在失败时降级，而不是整个流程中断。

3. **工程目标**
   - 所有节点围绕统一 `PlanState` 流转；
   - LLM 输出必须结构化并通过 Pydantic schema 校验；
   - 工具调用统一接入 timeout、retry、fallback、trace；
   - Runtime 数据可落 MySQL，并保留文件 fallback；
   - 提供 Trace、节点耗时、Memory、Checkpoint、Eval 测试；
   - 前端通过 SSE 展示 Agent 推理和规划过程。

### A：Action 关键行动

#### A1. 用 LangGraph 设计多 Agent DAG，而不是把逻辑写成单个大函数

我把规划过程拆成一条可观测、可回退的 DAG：

```text
Intent Router
-> Intent Parser
-> Constraint Builder
-> Constraint Clarifier
-> Planner Agent
-> POI Collector
-> 并行 Skills
-> Route & Time Planner
-> Availability Checker
-> Verifier
-> LLM Critic
-> Ranker
-> Response Generator
-> User Confirm
-> Execution Agent
```

核心文件：

- `backend/app/dag/langgraph_dag_config.py`
- `backend/app/state/plan_state.py`
- `backend/app/agents/*.py`
- `backend/app/tools/*.py`

这样做的原因是：Agent 项目最大的问题不是“能不能生成答案”，而是“出了问题能不能定位是哪一步错了”。DAG 拆分后，每个节点都有明确职责、输入输出和 trace 记录。

#### A2. 用 LLM 做语义理解，但不让 LLM 编造事实

项目中 LLM 主要用于：

- Intent / Constraint Understanding；
- Planner DAG 策略选择；
- Revision Parser；
- Memory Extractor；
- LLM Critic；
- Response 文案增强。

但 LLM 不直接生成 POI、价格、路线、天气和执行结果。这些事实必须来自：

- MySQL POI；
- 高德路线 / 天气；
- Route Planner；
- Verifier；
- PlanState 结构化字段。

相关文件：

- `backend/app/agents/llm_understanding.py`
- `backend/app/services/llm_service.py`
- `backend/app/services/llm_output_schemas.py`
- `backend/app/prompts/*.md`
- `backend/app/services/prompt_registry.py`

我把 Prompt 外置到 `backend/app/prompts`，并用 `PromptRegistry` 记录 prompt 版本和 schema 版本，避免 Prompt 散落在代码里无法评审、无法灰度。

#### A3. Collector 和 Skill 分层，避免推荐逻辑和数据读取耦合

系统支持七类 POI：

- 景点；
- 购物；
- 活动；
- 餐厅；
- 健身；
- 娱乐；
- 美容养生。

Collector 只负责从 MySQL 拉取候选并统一字段；Skill 负责按业务规则和用户约束打分。这样后续接入真实美团、高德、点评或内部 POI 服务时，只需要替换 Collector 或 Repository，不需要重写规划 DAG。

相关文件：

- `backend/app/agents/poi_collector.py`
- `backend/app/services/poi_repository.py`
- `backend/app/tools/poi_schema.py`
- `backend/app/tools/poi_activity_recommend.py`
- `backend/app/tools/poi_restaurant_recommend.py`
- `backend/app/tools/poi_lifestyle_recommend.py`
- `backend/app/tools/poi_mix_recommend.py`

业务上，餐厅不是只按评分排序，而是会综合预算、人均、场景、标签、距离、活动组合；娱乐类会关注 KTV、棋牌、电影等活动语义；活动和景点会考虑时间、室内/室外、适配关系和路线。

#### A4. 从“推荐 POI”升级到“生成可执行时间线”

本地生活规划的核心不是推荐单点，而是组合：

- 先去哪；
- 每站停多久；
- 两站之间怎么移动；
- 总时间是否超出；
- 预算是否可接受；
- 方案之间是否真的不同。

因此我实现了 Route & Time Planner，把候选 POI 组合成多套方案，并生成：

- `items`
- `timeline`
- `route_segments`
- `estimated_budget`
- `total_duration_minutes`
- `route_minutes`
- `fit_summary`

相关文件：

- `backend/app/agents/route_planner.py`
- `backend/app/services/amap_route_service.py`
- `backend/app/services/amap_weather_service.py`

高德路线失败时会回退 Haversine 估算，避免外部 API 失败导致 demo 或主链路不可用。

#### A5. 加 Verifier / LLM Critic，把“看起来合理”变成“可校验”

Verifier 负责确定性校验：

- 候选为空；
- 预算超出；
- 路线过长；
- 总时长超出；
- 类别重复；
- 营业未知；
- 预约风险。

LLM Critic 负责软性审查：

- 方案节奏是否自然；
- 是否符合情侣 / 朋友 / 家庭场景；
- 备选方案是否差异太小；
- 文案是否和结构化时间线矛盾。

相关文件：

- `backend/app/agents/verifier.py`
- `backend/app/agents/llm_critic.py`
- `backend/app/agents/ranker.py`

这样能把 Agent 的“主观生成”变成“结构化校验 + 软性 QA”，更接近生产系统里的评审链路。

#### A6. 做上下文治理，不把所有历史和工具结果塞进 Prompt

Agent 很容易因为上下文越来越长导致 Context Rot。项目里通过 `ContextBuilder` 生成结构化上下文：

- Current Intent；
- User Constraints；
- Planning State；
- Tool Evidence top-k；
- Conversation Summary；
- Prompt Meta。

硬约束永远保留，比如人数、预算、指定地点、排除词；候选 POI 和工具结果只保留摘要和 top-k，完整结果放在 state、runtime store 或 trace 中。

相关文件：

- `backend/app/services/context_builder.py`
- `backend/app/state/plan_state.py`
- `backend/app/services/memory_service.py`

这体现的是生产 Agent 的一个关键原则：**prompt 不应该是聊天历史拼接，而应该是由结构化 state 重建出来的任务上下文**。

#### A7. 做 Memory、Session、Checkpoint，支持多轮修改和任务恢复

项目实现了几层记忆：

- 用户长期画像：常用城市、预算偏好、喜欢/不喜欢类别；
- 会话内记忆：用户拒绝过的方案、当前选中方案、最近修改；
- 工具缓存：路线、天气、POI、执行结果；
- Milvus 向量记忆接口：用于语义检索和相似画像。

用户中途说“不要室外了，今天太热”，系统不是把它当成全新请求，而是通过 session state 和 revision parser 合并到已有约束中。

相关文件：

- `backend/app/services/memory_service.py`
- `backend/app/services/memory_store.py`
- `backend/app/services/vector_memory_store.py`
- `backend/app/services/session_store.py`
- `backend/app/services/checkpoint_store.py`
- `backend/app/services/trip_services.py`

Checkpoint 用于规划和执行恢复，避免页面刷新、服务重启或执行中断后重复执行已成功的动作。

#### A8. 做 ToolHarness 和 ToolPolicy，控制工具调用风险

Agent 接工具以后，最大风险是工具乱调、失败不可控、交易动作重复执行。所以我把工具分级：

- Level 0：内部推理；
- Level 1：查询工具；
- Level 2：日历、分享等轻状态变更；
- Level 3：预订、取消等交易动作；
- Level 4：支付、退款。

所有外部 I/O 都尽量通过 ToolHarness：

- LLM；
- MySQL；
- 高德路线；
- 高德天气；
- PDF；
- ICS；
- mock 执行。

工具结果统一记录：

- source；
- fetched_at；
- expires_at；
- confidence；
- fallback_used；
- attempts；
- latency_ms；
- error_code。

相关文件：

- `backend/app/services/tool_harness.py`
- `backend/app/services/tool_policy.py`
- `backend/app/services/trace_recorder.py`

这部分是我会在资深岗位面试中重点讲的：**Agent 不只是 prompt，工具治理、幂等、确认、fallback 和 trace 才是能不能上线的关键**。

#### A9. 前端做产品化交互，而不是只显示 JSON

前端采用 React + TypeScript + Vite，页面是“左侧方案工作台 + 右侧对话助手”：

- 对话区：用户输入、Agent 回复、流式状态；
- 方案区：3 个方案、优缺点、路线、时间线、POI 卡片；
- 地图区：高德 JS 地图、地点标注、路线展示；
- 执行区：预约、购票、打车、日历、PDF 分享；
- 观测面板：LLM 调用、工具调用、节点耗时、trace。

相关文件：

- `frontend/src/pages/PlannerWorkspace.tsx`
- `frontend/src/components/ChatAssistantPanel.tsx`
- `frontend/src/components/AmapRouteCard.tsx`
- `frontend/src/pages/ObservabilityPage.tsx`
- `frontend/src/api/streamClient.ts`

这使得项目不是命令行 demo，而是更接近真实产品。

#### A10. 做工程化验证和交付

项目不是只跑通主流程，还补了：

- 后端测试；
- 前端 build；
- Docker Compose；
- 中文 PDF；
- Prompt 外置；
- README 和详细文档；
- MySQL runtime schema；
- Milvus standalone；
- 兼容旧前端 API。

当前已验证：

- 后端测试：`109 passed`
- 前端构建：`npm run build` 通过
- 后端健康检查：`GET /health` 返回 `{"status":"ok"}`

### R：Result 结果

从工程结果看，项目已经形成一个较完整的 AI Agent 原型：

1. **业务闭环**
   - 用户可以输入自然语言；
   - 系统返回多个本地生活方案；
   - 每个方案包含 POI、时间线、路线、预算、优缺点；
   - 支持分享、PDF、日历和 mock 执行；
   - 支持中途修改需求。

2. **Agent 能力**
   - 支持简单问答、单类推荐、完整规划三种模式；
   - 支持多 Agent DAG；
   - 支持 LLM 语义理解 + 规则 fallback；
   - 支持 Verifier / Critic；
   - 支持 Memory 和 Context Governance。

3. **工程能力**
   - 有统一 `PlanState`；
   - 有 ToolHarness / ToolPolicy；
   - 有 RuntimeStore / Checkpoint；
   - 有 Trace / Node Metrics；
   - 有 Prompt Registry；
   - 有 MySQL + Milvus + Docker Compose；
   - 有测试和文档。

4. **业务价值表达**
   - 用户侧：从“自己搜地点、自己拼路线”变成“一句话得到可执行方案”；
   - 平台侧：方案可保存、分享、预约，天然承接转化链路；
   - 工程侧：规划、工具、记忆、恢复和观测分层，为后续接真实履约 API 打基础；
   - 数据侧：Trace 和用户行为可以反哺推荐、评测和产品指标。

目前真实业务转化数据还没有，因为这是项目原型；但系统已经预留了可度量指标：

- 方案保存率；
- 分享率；
- 导航点击率；
- mock 预约转化；
- 用户修改次数；
- 方案拒绝原因；
- 工具失败率；
- 缓存命中率；
- 节点耗时；
- Verifier 通过率。

## 3. 面试中可以重点展开的技术点

### 3.1 为什么用 LangGraph，而不是普通链式调用？

回答要点：

- 普通链式调用适合线性任务，但本地生活规划有分支、并行、回退和状态累积；
- LangGraph 可以把每个 Agent 节点显式化；
- `PlanState` 作为统一状态对象，方便节点之间传递结构化结果；
- 可以在 Verifier 不通过时回退 Planner 或 Skill；
- 每个节点可以单独 trace、测试和优化。

### 3.2 LLM 在系统里负责什么，不负责什么？

负责：

- 意图识别；
- 约束抽取；
- Planner 策略；
- 中途修改解析；
- Memory 抽取；
- 软性 Critic；
- 文案增强。

不负责：

- 编造 POI；
- 编造价格；
- 编造路线；
- 编造天气；
- 编造预约成功结果。

这些事实必须来自数据库、工具或结构化 state。

### 3.3 如何防止 Agent 胡编？

项目做了几层限制：

- LLM 输出必须通过 Pydantic schema；
- Prompt 明确禁止新增地点、路线、价格；
- Response Generator 只基于 `ranked_plans`；
- Verifier 检查预算、时长、路线；
- ToolHarness 记录工具来源和 fallback；
- Trace 可以复盘每次决策。

### 3.4 如何处理多轮对话？

不是把完整聊天历史都塞给 LLM，而是：

- 用 `session_id` 找到上一轮 `PlanState`；
- 用 Revision Parser 把新输入解析成约束 patch；
- 合并到当前 intent / constraints；
- 必要时局部替换 POI 或重跑后半段 DAG；
- 保存 revision 和 checkpoint。

### 3.5 如何设计 Memory？

我把 Memory 分成三层：

- User Profile Memory：长期偏好；
- Session Memory：当前会话状态；
- Tool Cache：路线、天气、POI、执行结果。

Memory 是软约束，本轮用户明确输入永远优先，避免历史偏好污染当前需求。

### 3.6 如何设计工具安全？

工具按风险分级：

- 查询类可以自动调用；
- 日历、分享属于轻状态变更；
- 预订、取消必须有确认；
- 支付、退款不自动执行。

Level 3+ 动作必须有幂等键，避免重复下单。

## 4. 简历项目描述

### 简历版本 1：偏业务 + 架构

设计并实现 LifeRouteAgent 本地生活规划 Agent，面向家庭、朋友、情侣周末活动场景，将自然语言需求转化为带 POI、路线、时间线、预算和执行入口的可落地方案。后端基于 FastAPI + LangGraph + MySQL 构建多 Agent DAG，包含 Intent Router、Planner、Collector、并行 Skill、Route Planner、Verifier、LLM Critic、Ranker 和 Response Generator；前端基于 React + SSE 实现流式规划、方案卡片、地图路线、Trace 观测和 mock 执行。系统接入 ToolHarness、ToolPolicy、Memory、Checkpoint、Prompt Registry 和 RuntimeStore，支持中途修改、PDF/ICS 导出、节点耗时追踪和后端自动化测试。

### 简历版本 2：偏高级 AI Agent 工程

主导实现一个具备生产化雏形的本地生活 AI Agent 系统：使用 LangGraph 将规划任务拆解为可观测 DAG，以 `PlanState` 管理全局状态；LLM 负责意图理解、Planner 策略、Revision、Critic 和响应增强，所有输出经 Pydantic schema 校验，避免非结构化结果污染状态；工具侧统一封装 ToolHarness，实现 timeout、retry、fallback、trace 和风险分级；记忆侧实现用户画像、会话记忆、工具缓存和 Milvus 向量记忆接口；运行态支持 MySQL RuntimeStore、Checkpoint 恢复和节点耗时指标。该项目体现了 Agent 从 demo 到工程化系统所需的上下文治理、工具治理、记忆设计、评测与可观测性能力。

### 简历版本 3：偏可落地产品

开发 LifeRouteAgent 本地生活规划平台，支持用户用自然语言描述“周末和朋友出去玩”“情侣去环球影城再唱歌”等需求，系统自动生成 3 个可执行方案，包含地点推荐、推荐理由、优缺点、时间线、交通路线、预算估算和执行操作。实现简单问答、单类推荐、完整规划三种模式；支持高德地图/天气、MySQL POI、中文 PDF 导出、日历 ICS、mock 预约/购票/打车、方案局部调整和观测面板。后端测试覆盖核心流程，前端构建通过，提供 Docker Compose 支持 MySQL、Milvus、后端和前端一键启动。

## 5. 面试 5 分钟讲稿

我这个项目叫 LifeRouteAgent，是一个本地生活规划 Agent。它解决的问题是：用户周末想出去玩时，通常不是只想搜一个地点，而是要同时考虑和谁去、去哪、先后顺序、路线、预算、时间、天气、排队和预约。传统搜索只能返回地点列表，普通聊天机器人又容易只给一段不可执行的建议。所以我做的是一个从自然语言到可执行方案的 Agent 系统。

系统的输入是一句话，比如“明天和对象去环球影城，然后去唱歌，两个人预算 1000”。后端会先用 LLM 做意图和约束理解，判断这是完整规划，不是简单问答；然后提取人数、预算、必须地点、活动语义等字段。接着进入 LangGraph DAG，Planner Agent 会选择本次需要查哪些类别、启用哪些 Skill，以及采用什么 slot sequence。POI Collector 从 MySQL 七类 POI 表里召回候选，餐厅、活动、娱乐、景点商场等 Skill 并行打分，Route Planner 再把候选组合成带时间线和路线段的方案。

我在架构上比较强调边界。LLM 只负责语义理解、策略选择、Critic 和文案增强，不允许它编造 POI、价格、路线和预约结果。真实事实必须来自 MySQL、高德路线、高德天气或 PlanState。所有 LLM 输出都要过 Pydantic schema，Prompt 也已经外置到 prompts 目录，并通过 PromptRegistry 记录版本。

为了让方案不是“看起来合理”而是真的可执行，我加了 Verifier 和 LLM Critic。Verifier 检查预算、路线、总时长、候选为空、营业未知等确定性问题；LLM Critic 负责判断方案节奏、同行关系和备选方案差异。Ranker 最后按整体方案分排序，而不是只按单个 POI 评分排序。

工程治理方面，我实现了 ToolHarness 和 ToolPolicy。所有外部 I/O，比如 LLM、MySQL、高德路线、高德天气、PDF、ICS、mock 执行，都尽量统一经过 timeout、retry、fallback 和 trace。工具按风险分级，查询可以自动执行，日历和分享是轻状态变更，预订和取消必须有确认和幂等键，支付类动作目前不自动执行。

我还做了 Memory 和上下文治理。系统不会把完整聊天历史和所有工具结果塞进 prompt，而是通过 ContextBuilder 生成结构化上下文，只保留当前 intent、硬约束、软偏好、top-k 工具证据和会话摘要。Memory 分成长期画像、会话记忆和工具缓存，用户中途说“不要室外了，今天太热”，系统会基于已有 state 修正方案，而不是当成一个全新请求。

前端是 React + Vite，左侧展示方案、地图、路线、时间线和 POI 卡片，右侧是对话助手，通过 SSE 接收后端流式事件。还有观测面板，可以看到 LLM 调用、工具调用、节点耗时和 trace。项目目前真实订座、购票、打车还是 mock，但已经实现中文 PDF、ICS 日历、Docker Compose、MySQL runtime、Milvus 接口和后端测试。

总结来说，这个项目不是一个单纯的 LLM demo，而是围绕 Agent 工程化做了一套完整原型：自然语言理解、POI 召回、推荐排序、路线规划、可执行校验、工具治理、记忆、恢复、观测和评测。后续如果接入真实库存、订座、票务和支付，它可以继续演进成更接近生产级的本地生活规划系统。

## 6. 面试官可能深挖的问题与回答

### Q1：为什么说这是 Agent，而不是普通推荐系统？

因为它不是只做一次检索排序，而是有明确的感知、决策、行动和反馈循环。系统先理解用户意图，再动态选择 Skill 和规划模板，然后调用数据库、路线、天气等工具，生成方案后由 Verifier/Critic 检查，不通过时可以回退调整。状态通过 `PlanState` 在 DAG 中流转，而不是一次性函数调用。

### Q2：为什么不用 LLM 直接生成方案？

直接生成会有幻觉风险，比如编造地点、价格、路线和营业状态。本项目让 LLM 做语义理解和表达增强，事实数据来自 MySQL 和工具。这样既保留 LLM 的理解能力，又把业务事实控制在可验证的数据源里。

### Q3：你怎么处理用户追问或中途修改？

通过 `session_id` 和 `SessionStore` 保存上一轮 `PlanState`。用户说“不要室外了”时，Revision Parser 把这句话解析成结构化约束 patch，再合并到当前 constraints，局部替换或重跑后半段 DAG，不把它当成全新请求。

### Q4：ToolHarness 的价值是什么？

它把工具调用变成统一治理对象。每个工具都有 timeout、retry、fallback、source、latency、attempts、error_code 和 trace。这样外部 API 失败时可以降级，同时便于排查“是模型问题、工具问题，还是数据问题”。

### Q5：Memory 会不会污染当前需求？

会有这个风险，所以项目里规定 Memory 是软约束，本轮用户明确输入优先级最高。比如用户长期偏室内，但这次明确说想去公园，就不能因为 Memory 把公园过滤掉。

### Q6：当前项目最大的不足是什么？

最大不足是真实履约 API 还没接入，订座、购票、打车目前是 mock。其次，Prompt 虽然外置了，但还没有灰度平台；Observability 还是本地 trace，没有接 OpenTelemetry；MySQL runtime 有初始化脚本，但还不是完整迁移体系。

### Q7：如果要上线，你下一步会做什么？

我会优先接真实库存/预约查询，但交易动作仍保持确认和幂等；然后接 OpenTelemetry、Prometheus 和日志平台；再补数据库 migration、权限体系、AB 实验、端到端评测和真实业务指标看板。

### Q8：怎么评测这个 Agent？

不能只评回答是否自然。我会分层评测：意图解析准确率、规划质量、工具调用正确性、履约安全、业务效果。项目里已经有测试和 eval 结构，后续可以补固定 benchmark 和 trace replay。

### Q9：为什么要有 Verifier 和 LLM Critic 两层？

Verifier 适合确定性规则，比如预算、时长、路线；LLM Critic 适合软性判断，比如情侣约会节奏是否自然、备选方案是否太像。两者分工不同，避免把所有判断都交给 LLM。

### Q10：高级 / 资深岗位最能体现你能力的点是什么？

不是会调用 LLM，而是能把 Agent 拆成可维护系统：状态、上下文、工具、安全、记忆、恢复、观测、评测都有工程边界。这个项目体现的是从 demo 到生产化原型的系统设计能力。

## 7. 可以在简历里强调的关键词

- Agentic Planning
- LangGraph DAG
- Multi-Agent Workflow
- PlanState 状态流
- LLM Schema Validation
- Prompt Registry
- Context Governance
- ToolHarness
- ToolPolicy / Risk Level
- Memory / Session / Checkpoint
- Milvus Vector Memory
- MySQL RuntimeStore
- SSE Streaming UX
- Verifier / Critic
- Trace / Node Metrics
- Mock Execution
- PDF / ICS Export

## 8. 项目一句话总结

我实现了一个面向本地生活场景的可执行规划 Agent，把用户自然语言需求转化为带 POI、路线、时间线、预算、校验、调整和执行入口的结构化方案，并围绕 LLM、工具、记忆、恢复和观测做了工程化治理。
