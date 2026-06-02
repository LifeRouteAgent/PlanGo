import { Baby, Building2, Heart, MapPin, PiggyBank, RefreshCw, TimerReset, UsersRound } from "lucide-react";
import { SoftTag } from "../../components/ui";

const chipGroups = [
  [
    { label: "家庭出行", icon: UsersRound },
    { label: "朋友聚会", icon: UsersRound },
    { label: "亲子", icon: Baby },
    { label: "室内", icon: Building2 },
    { label: "预算低", icon: PiggyBank },
    { label: "附近", icon: MapPin }
  ],
  [
    { label: "情侣约会", icon: Heart },
    { label: "轻松一点", icon: TimerReset },
    { label: "少排队", icon: UsersRound },
    { label: "别太远", icon: MapPin },
    { label: "预算适中", icon: PiggyBank },
    { label: "室内活动", icon: Building2 }
  ]
];

interface QuickChipsProps {
  selected?: string[];
  variant?: number;
  onToggle?: (value: string) => void;
  onRefresh?: () => void;
  onPick?: (value: string) => void;
}

export function QuickChips({ selected = [], variant = 0, onToggle, onRefresh, onPick }: QuickChipsProps) {
  const chips = chipGroups[variant % chipGroups.length];
  const handleToggle = (label: string) => {
    if (onToggle) {
      onToggle(label);
      return;
    }
    onPick?.(label);
  };

  return (
    <div className="quick-chips" aria-label="快捷偏好">
      {chips.map((chip) => {
        const Icon = chip.icon;
        return (
          <SoftTag key={chip.label} selected={selected.includes(chip.label)} onClick={() => handleToggle(chip.label)} tone="blue">
            <Icon size={15} />
            {chip.label}
          </SoftTag>
        );
      })}
      <button type="button" className="quick-chip-refresh" onClick={onRefresh} aria-label="换一批快捷偏好">
        <RefreshCw size={16} />
      </button>
    </div>
  );
}
