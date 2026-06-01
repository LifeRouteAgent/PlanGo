import { MapPin, Star, WalletCards, X } from "lucide-react";
import { AppleButton, SoftTag } from "../../components/ui";
import type { PlanStopView } from "../../utils/planViewModel";

interface PlaceDetailDrawerProps {
  stop: PlanStopView | null;
  onClose: () => void;
}

export function PlaceDetailDrawer({ stop, onClose }: PlaceDetailDrawerProps) {
  if (!stop) return null;

  return (
    <aside className="drawer" aria-label="地点详情">
      <div className="drawer-panel place-drawer">
        <header>
          <div>
            <span>地点详情</span>
            <h2>{stop.title}</h2>
          </div>
          <AppleButton type="button" variant="ghost" size="sm" onClick={onClose} aria-label="关闭地点详情">
            <X size={18} />
          </AppleButton>
        </header>
        <div className="place-cover">
          {stop.imageUrl ? <img src={stop.imageUrl} alt={stop.title} /> : <span>{stop.label}</span>}
        </div>
        <div className="drawer-content">
          <section className="drawer-section">
            <strong>推荐理由</strong>
            <p>{stop.reason}</p>
          </section>
          <div className="place-facts">
            <span>
              <MapPin size={16} />
              {stop.address}
            </span>
            {stop.rating && (
              <span>
                <Star size={16} />
                评分 {stop.rating}
              </span>
            )}
            <span>
              <WalletCards size={16} />
              {stop.cost ? `预算约 ¥${Math.round(stop.cost)}` : "预算待估"}
            </span>
            <span>{stop.traffic}</span>
          </div>
          <div className="tag-row">
            {stop.tags.length ? stop.tags.map((tag) => <SoftTag key={tag}>{tag}</SoftTag>) : <SoftTag>本地生活</SoftTag>}
          </div>
          <section className="drawer-section">
            <strong>出发前建议</strong>
            <p>营业、排队或预约信息可能随时间变化，建议出发前再次确认。PlanGo 会优先使用当前方案中的结构化数据，不会在前端编造地点信息。</p>
          </section>
        </div>
      </div>
    </aside>
  );
}
