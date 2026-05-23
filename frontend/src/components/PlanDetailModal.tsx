import { X } from "lucide-react";
import type { PlanAlternative, PlanStep } from "../types/agent";

export type DetailPayload =
  | { type: "step"; title: string; item: PlanStep }
  | { type: "alternative"; title: string; item: PlanAlternative }
  | { type: "alternatives"; title: string; items: PlanAlternative[] };

interface PlanDetailModalProps {
  detail: DetailPayload | null;
  onClose: () => void;
  onSelectAlternative?: (id: string) => void;
}

function fallbackImageClass(index = 0) {
  return ["science", "park", "museum", "play"][index % 4];
}

export function PlanDetailModal({ detail, onClose, onSelectAlternative }: PlanDetailModalProps) {
  if (!detail) {
    return null;
  }

  const items: Array<{ step?: PlanStep; alternative?: PlanAlternative }> =
    detail.type === "alternatives"
      ? detail.items.map((item) => ({ alternative: item }))
      : [{ step: detail.type === "step" ? detail.item : undefined, alternative: detail.type === "alternative" ? detail.item : undefined }];

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-label={detail.title}>
      <div className="detail-modal">
        <header>
          <div>
            <p className="eyebrow">详情</p>
            <h2>{detail.title}</h2>
          </div>
          <button type="button" className="icon-button" aria-label="关闭" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        <div className="detail-modal-body">
          {items.map(({ step, alternative }, index) => {
            const tags = step?.detail?.tags ?? alternative?.tags ?? [];
            const description = step?.detail?.description ?? alternative?.description ?? step?.reason ?? "";
            const address = step?.detail?.address ?? step?.location?.address ?? "";
            const cost = step?.detail?.cost ?? step?.cost;
            return (
              <article className="detail-card" key={step?.title ?? alternative?.id ?? index}>
                <div className={`detail-image ${fallbackImageClass(index)}`} />
                <div>
                  <h3>{step?.title ?? alternative?.title}</h3>
                  <p>{description}</p>
                  <div className="tag-cloud">
                    {tags.map((tag: string) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                  <dl className="detail-meta">
                    {step && (
                      <>
                        <div>
                          <dt>时间</dt>
                          <dd>
                            {step.start_time} - {step.end_time}
                          </dd>
                        </div>
                        <div>
                          <dt>交通</dt>
                          <dd>{step.detail?.traffic || "按高德路线估算"}</dd>
                        </div>
                      </>
                    )}
                    {alternative && (
                      <>
                        <div>
                          <dt>评分</dt>
                          <dd>{alternative.rating}</dd>
                        </div>
                        <div>
                          <dt>距离</dt>
                          <dd>{alternative.distance_km.toFixed(1)} 公里</dd>
                        </div>
                      </>
                    )}
                    <div>
                      <dt>费用</dt>
                      <dd>{typeof cost === "number" ? `¥${Math.round(cost)}` : "-"}</dd>
                    </div>
                    <div>
                      <dt>地址</dt>
                      <dd>{address || "详情中未提供"}</dd>
                    </div>
                  </dl>
                  {alternative && onSelectAlternative && (
                    <button
                      type="button"
                      className="primary-action modal-action"
                      onClick={() => onSelectAlternative(alternative.id)}
                    >
                      选择此备选方案
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      </div>
    </div>
  );
}
