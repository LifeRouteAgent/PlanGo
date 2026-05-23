import { Boxes, BrainCircuit, Radio, ShieldCheck } from "lucide-react";

const modules = [
  {
    icon: BrainCircuit,
    title: "规划策略",
    text: "按意图识别、场景判断、候选召回、多目标排序、时间线编排和方案校验分层处理。"
  },
  {
    icon: Boxes,
    title: "工具端口",
    text: "搜索、路线、库存、预订和取消都通过端口抽象，当前接口可替换为真实服务。"
  },
  {
    icon: ShieldCheck,
    title: "失败恢复",
    text: "执行链路保留补偿语义，后续动作失败时可以补偿已确认订单。"
  },
  {
    icon: Radio,
    title: "流式体验",
    text: "后端通过 SSE 分阶段输出事件，前端增量展示 Agent 的决策、约束和执行状态。"
  }
];

const flowSteps = ["意图识别", "候选召回", "排序", "时间线", "校验", "执行", "补偿"];

export function ArchitecturePage() {
  return (
    <div className="architecture-page">
      <section className="page-heading">
        <p className="eyebrow">系统架构</p>
        <h1>LifeRoute Agent 架构</h1>
        <p>前端关注可解释体验，后端保持领域模型、应用编排和工具基础设施解耦。</p>
      </section>

      <section className="architecture-grid">
        {modules.map((module) => {
          const Icon = module.icon;
          return (
            <article className="architecture-card" key={module.title}>
              <Icon size={24} />
              <h2>{module.title}</h2>
              <p>{module.text}</p>
            </article>
          );
        })}
      </section>

      <section className="panel flow-panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">执行链路</p>
            <h2>流式规划流程</h2>
          </div>
        </div>
        <div className="flow-line">
          {flowSteps.map((step) => (
            <span key={step}>{step}</span>
          ))}
        </div>
      </section>
    </div>
  );
}
