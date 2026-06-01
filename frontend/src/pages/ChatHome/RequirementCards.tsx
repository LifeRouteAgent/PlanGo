import { Baby, Coffee, MapPin, Sparkles, UsersRound } from "lucide-react";

const cards = [
  {
    title: "朋友聚会 4 小时",
    text: "周末下午和朋友出去玩，想吃饭、唱歌或桌游，预算适中，别太远。",
    icon: UsersRound
  },
  {
    title: "亲子室内半日",
    text: "适合孩子，少排队，路线简单，最好有亲子活动和餐厅。",
    icon: Baby
  },
  {
    title: "低预算附近放松",
    text: "找轻松、不赶路的活动，控制花费，适合临时出门。",
    icon: Coffee
  }
];

interface RequirementCardsProps {
  onPick: (value: string) => void;
}

export function RequirementCards({ onPick }: RequirementCardsProps) {
  return (
    <section className="requirement-cards" aria-label="需求示例">
      {cards.map((card, index) => {
        const Icon = card.icon;
        return (
          <button
            type="button"
            className="requirement-card"
            key={card.title}
            onClick={() => onPick(card.text)}
            style={{ animationDelay: `${0.22 + index * 0.04}s` }}
          >
            <Icon size={20} />
            <span>
              <strong>{card.title}</strong>
              <small>{card.text}</small>
            </span>
            {index === 0 ? <Sparkles size={16} aria-hidden="true" /> : <MapPin size={16} aria-hidden="true" />}
          </button>
        );
      })}
    </section>
  );
}
