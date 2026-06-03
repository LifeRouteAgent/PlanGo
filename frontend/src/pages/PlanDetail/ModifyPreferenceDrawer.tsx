import { SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { AppleButton, SoftTag } from "../../components/ui";
import type { PlanStopView, PlanViewModel } from "../../utils/planViewModel";

interface ModifyPreferenceDrawerProps {
  open: boolean;
  targetStop: PlanStopView | null;
  plan: PlanViewModel | null;
  onClose: () => void;
  onApply: (message: string) => void;
}

const groups = [
  { title: "节奏", options: ["轻松一点", "紧凑一点", "时间短一点"] },
  { title: "预算", options: ["更省钱", "预算提高一点", "保持当前预算"] },
  { title: "距离", options: ["更近一点", "少换地方", "同商圈优先"] },
  { title: "人群", options: ["更适合情侣", "更适合朋友", "更适合家庭"] },
  { title: "饮食", options: ["晚餐清淡一点", "不要火锅", "加一个咖啡甜品"] },
  { title: "环境", options: ["换成室内", "少排队", "适合拍照"] }
];

function stopScope(stop: PlanStopView | null) {
  if (!stop) return "方案";
  const numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九"];
  return `第${numerals[stop.order - 1] ?? stop.order}个地点`;
}

export function ModifyPreferenceDrawer({ open, targetStop, plan, onClose, onApply }: ModifyPreferenceDrawerProps) {
  const [selected, setSelected] = useState<string[]>([]);
  if (!open) return null;

  const toggle = (value: string) => {
    setSelected((current) => (current.includes(value) ? current.filter((item) => item !== value) : [...current, value]));
  };

  const apply = () => {
    const scope = stopScope(targetStop);
    onApply(`${scope}${selected.join("，") || "调整一下"}`);
    setSelected([]);
    onClose();
  };

  return (
    <aside className="drawer" aria-label="调整偏好">
      <div className="drawer-panel preference-drawer">
        <header>
          <div>
            <h2>{targetStop ? `调整 ${targetStop.title}` : "调整当前方案"}</h2>
          </div>
          <AppleButton type="button" variant="ghost" size="sm" onClick={onClose} aria-label="关闭调整偏好">
            <X size={18} />
          </AppleButton>
        </header>
        <div className="drawer-content">
          {groups.map((group) => (
            <section className="preference-group" key={group.title}>
              <strong>{group.title}</strong>
              <div>
                {group.options.map((option) => (
                  <SoftTag selected={selected.includes(option)} key={option} onClick={() => toggle(option)}>
                    {option}
                  </SoftTag>
                ))}
              </div>
            </section>
          ))}
          <AppleButton type="button" full onClick={apply} disabled={!selected.length}>
            <SlidersHorizontal size={18} />
            应用调整
          </AppleButton>
        </div>
      </div>
    </aside>
  );
}
