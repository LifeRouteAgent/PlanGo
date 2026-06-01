import { Baby, Building2, MapPin, PiggyBank, UsersRound } from "lucide-react";
import { SoftTag } from "../../components/ui";

const chips = [
  { label: "家庭出行", icon: UsersRound },
  { label: "朋友聚会", icon: UsersRound },
  { label: "亲子", icon: Baby },
  { label: "室内", icon: Building2 },
  { label: "预算低", icon: PiggyBank },
  { label: "附近", icon: MapPin }
];

interface QuickChipsProps {
  onPick: (value: string) => void;
}

export function QuickChips({ onPick }: QuickChipsProps) {
  return (
    <div className="quick-chips" aria-label="快捷偏好">
      {chips.map((chip) => {
        const Icon = chip.icon;
        return (
          <SoftTag key={chip.label} onClick={() => onPick(chip.label)} tone="blue">
            <Icon size={15} />
            {chip.label}
          </SoftTag>
        );
      })}
    </div>
  );
}
