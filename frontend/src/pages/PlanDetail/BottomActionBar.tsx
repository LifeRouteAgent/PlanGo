import { CheckCircle2, Download, Home, Loader2, PlayCircle, SlidersHorizontal, X } from "lucide-react";
import { useMemo, useState } from "react";
import { bookPlan, downloadPreparedPlanPdf, exportPlanPdf } from "../../api/streamClient";
import type { PlanViewModel } from "../../utils/planViewModel";

interface BottomActionBarProps {
  plan: PlanViewModel;
  pdfToken?: string;
  pdfPreparing?: boolean;
  pdfPrepareError?: string;
  onBackHome: () => void;
  onShare: () => void;
  onModify: () => void;
}

export function BottomActionBar({ plan, pdfToken = "", pdfPreparing = false, pdfPrepareError = "", onBackHome, onModify }: BottomActionBarProps) {
  const [executeOpen, setExecuteOpen] = useState(false);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [downloadFallbackRunning, setDownloadFallbackRunning] = useState(false);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);

  const executeSteps = useMemo(() => {
    const actions = plan.raw.actions?.length
      ? plan.raw.actions.map((action) => {
          if (action.action_type.includes("restaurant")) return `预约餐厅：${action.target_name}`;
          if (action.action_type.includes("ticket")) return `锁定票务：${action.target_name}`;
          if (action.action_type.includes("taxi")) return `准备打车：${action.target_name}`;
          return `执行动作：${action.target_name}`;
        })
      : [];
    const fallbackSteps = actions.length ? [] : ["模拟预约餐厅", "模拟锁定票务", "准备打车路线"];
    return [...actions, ...fallbackSteps, "生成日历文件"].slice(0, 5);
  }, [plan.raw.actions]);

  const startExecution = async () => {
    setRunning(true);
    setDone(false);
    for (let index = 0; index < executeSteps.length; index += 1) {
      setActiveIndex(index);
      await new Promise((resolve) => window.setTimeout(resolve, 760));
    }
    await bookPlan(plan.id).catch(() => null);
    setActiveIndex(executeSteps.length);
    setDone(true);
    setRunning(false);
  };

  const closeExecution = () => {
    if (running) return;
    setExecuteOpen(false);
    setDone(false);
    setActiveIndex(-1);
  };

  const confirmDownload = async () => {
    if (pdfToken) {
      downloadPreparedPlanPdf(pdfToken);
      setDownloadOpen(false);
      return;
    }
    if (pdfPreparing) return;
    setDownloadFallbackRunning(true);
    try {
      await exportPlanPdf(plan.raw);
      setDownloadOpen(false);
    } finally {
      setDownloadFallbackRunning(false);
    }
  };

  return (
    <>
      <div className="bottom-action-bar">
        <button type="button" onClick={onBackHome}>
          <Home size={17} />
          继续对话
        </button>
        <button type="button" onClick={onModify}>
          <SlidersHorizontal size={17} />
          调整偏好
        </button>
        <button type="button" onClick={() => setDownloadOpen(true)}>
          <Download size={17} />
          导出 PDF
        </button>
        <button type="button" className="primary" onClick={() => setExecuteOpen(true)}>
          <PlayCircle size={17} />
          执行计划
        </button>
      </div>

      {executeOpen ? (
        <div className="execute-modal-backdrop" role="presentation" onMouseDown={closeExecution}>
          <section
            className="execute-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="execute-plan-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button type="button" className="execute-modal-close" onClick={closeExecution} disabled={running} aria-label="关闭执行弹窗">
              <X size={16} />
            </button>
            <h3 id="execute-plan-title">{done ? "执行完成" : "确定执行这个方案？"}</h3>
            <p>
              {done
                ? "模拟预约、票务、打车和日历动作已完成。"
                : "点击确认后，PlanGo 会按顺序调用 mock-api 演示预约、购票、打车和日历流程。"}
            </p>
            <div className="execute-step-list">
              {executeSteps.map((step, index) => {
                const finished = done || activeIndex > index;
                const active = running && activeIndex === index;
                return (
                  <div className={`execute-step ${finished ? "is-done" : ""} ${active ? "is-active" : ""}`} key={step}>
                    <span>{finished ? <CheckCircle2 size={17} /> : active ? <Loader2 size={17} className="spin" /> : index + 1}</span>
                    <strong>{step}</strong>
                    <small>{finished ? "已完成" : active ? "执行中" : "等待中"}</small>
                  </div>
                );
              })}
            </div>
            <div className="execute-modal-actions">
              {!done ? (
                <>
                  <button type="button" className="confirm-dialog-secondary" onClick={closeExecution} disabled={running}>
                    取消
                  </button>
                  <button type="button" className="confirm-dialog-danger execute-confirm" onClick={() => void startExecution()} disabled={running}>
                    {running ? "执行中" : "确认执行"}
                  </button>
                </>
              ) : (
                <button type="button" className="confirm-dialog-danger execute-confirm" onClick={closeExecution}>
                  确定
                </button>
              )}
            </div>
          </section>
        </div>
      ) : null}

      {downloadOpen ? (
        <div className="execute-modal-backdrop" role="presentation" onMouseDown={() => !downloadFallbackRunning && setDownloadOpen(false)}>
          <section
            className="execute-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="download-plan-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <button type="button" className="execute-modal-close" onClick={() => setDownloadOpen(false)} disabled={downloadFallbackRunning} aria-label="关闭下载弹窗">
              <X size={16} />
            </button>
            <h3 id="download-plan-title">下载 PDF 文件</h3>
            <p>
              {pdfToken
                ? "方案文档已准备好。点击确定后，浏览器会直接下载 PDF 文件。"
                : pdfPreparing
                  ? "方案文档正在后台生成，请稍等片刻。准备完成后点击确定即可下载。"
                  : pdfPrepareError
                    ? "预渲染未完成，将为你现场生成并下载，可能需要稍等。"
                    : "点击确定后将下载 PDF 文件。"}
            </p>
            <div className="execute-modal-actions">
              <button type="button" className="confirm-dialog-secondary" onClick={() => setDownloadOpen(false)} disabled={downloadFallbackRunning}>
                取消
              </button>
              <button type="button" className="confirm-dialog-danger execute-confirm" onClick={() => void confirmDownload()} disabled={pdfPreparing || downloadFallbackRunning}>
                {downloadFallbackRunning ? "生成中" : pdfPreparing ? "准备中" : "确定下载"}
              </button>
            </div>
          </section>
        </div>
      ) : null}
    </>
  );
}
