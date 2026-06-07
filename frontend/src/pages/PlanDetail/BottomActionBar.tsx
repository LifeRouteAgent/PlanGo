import { CheckCircle2, Download, Home, Loader2, PlayCircle, Share2, SlidersHorizontal, X } from "lucide-react";
import { useMemo, useState } from "react";
import { buildMockExecutionSteps, executeMockPlan, exportPlanPdf, type MockExecutionResult } from "../../api/streamClient";
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

export function BottomActionBar({
  plan,
  pdfPreparing = false,
  pdfPrepareError = "",
  onBackHome,
  onShare,
  onModify
}: BottomActionBarProps) {
  const [executeOpen, setExecuteOpen] = useState(false);
  const [downloadOpen, setDownloadOpen] = useState(false);
  const [downloadFallbackRunning, setDownloadFallbackRunning] = useState(false);
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [executionResults, setExecutionResults] = useState<Record<number, MockExecutionResult>>({});

  const executeSteps = useMemo(() => buildMockExecutionSteps(plan.raw), [plan.raw]);

  const startExecution = async () => {
    setRunning(true);
    setDone(false);
    setExecutionResults({});
    try {
      await executeMockPlan(
        plan.raw,
        (index) => setActiveIndex(index),
        (index, result) => {
          setExecutionResults((current) => ({ ...current, [index]: result }));
          setActiveIndex(index + 1);
        }
      );
      setDone(true);
    } finally {
      setRunning(false);
    }
  };

  const closeExecution = () => {
    if (running) return;
    setExecuteOpen(false);
    setDone(false);
    setActiveIndex(-1);
    setExecutionResults({});
  };

  const confirmDownload = async () => {
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
        <button type="button" onClick={onShare}>
          <Share2 size={17} />
          分享方案
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
                ? "餐厅预约、票务锁定、打车准备和日历提醒已通过 mock API 完成。"
                : "点击确认后，PlanGo 会按顺序调用后端 mock API，返回订单号和执行状态。"}
            </p>
            <div className="execute-step-list">
              {executeSteps.map((step, index) => {
                const result = executionResults[index];
                const finished = Boolean(result);
                const active = running && activeIndex === index;
                return (
                  <div className={`execute-step ${finished ? "is-done" : ""} ${active ? "is-active" : ""}`} key={step.id}>
                    <span>{finished ? <CheckCircle2 size={17} /> : active ? <Loader2 size={17} className="spin" /> : index + 1}</span>
                    <strong>{step.label}</strong>
                    <small>{result?.order_id || result?.message || (active ? "调用中" : "等待中")}</small>
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
              {pdfPreparing
                ? "方案文档正在后台生成，请稍等片刻。"
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
