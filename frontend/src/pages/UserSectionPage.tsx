import { Calendar, Heart, History, User } from "lucide-react";
import { useEffect, useState } from "react";
import { getUserSection } from "../api/streamClient";
import type { AppView } from "../App";

interface UserSectionPageProps {
  section: Exclude<AppView, "planner" | "plans">;
}

const sectionMeta = {
  favorites: { title: "收藏夹", description: "查看已收藏的生活规划。", icon: Heart },
  history: { title: "历史记录", description: "回顾最近生成过的规划。", icon: History },
  calendar: { title: "日历", description: "查看已加入日历的行程。", icon: Calendar },
  profile: { title: "个人中心", description: "查看当前用户资料和偏好。", icon: User }
} as const;

export function UserSectionPage({ section }: UserSectionPageProps) {
  const meta = sectionMeta[section];
  const Icon = meta.icon;
  const [status, setStatus] = useState("正在加载...");
  const [items, setItems] = useState<Array<Record<string, unknown>>>([]);

  useEffect(() => {
    getUserSection(section)
      .then((payload) => {
        const data = payload as { items?: Array<Record<string, unknown>>; profile?: Record<string, unknown> };
        if (data.profile) {
          setItems([data.profile]);
        } else {
          setItems(data.items ?? []);
        }
        setStatus("已加载");
      })
      .catch((error) => setStatus((error as Error).message));
  }, [section]);

  return (
    <div className="section-page">
      <section className="page-heading">
        <p className="eyebrow">用户中心</p>
        <h1>{meta.title}</h1>
        <p>{meta.description}</p>
      </section>

      <section className="panel">
        <div className="panel-header">
          <div>
            <p className="eyebrow">{status}</p>
            <h2>{items.length ? "内容列表" : "暂无内容"}</h2>
          </div>
          <Icon size={24} />
        </div>
        <div className="user-section-list">
          {items.map((item, index) => (
            <article className="user-section-row" key={`${section}-${index}`}>
              <strong>{String(item.title ?? item.name ?? meta.title)}</strong>
              <span>{String(item.start_time ?? item.city ?? item.updated_at ?? "暂无更多信息")}</span>
            </article>
          ))}
          {items.length === 0 && <p className="muted">完成规划或保存方案后，这里会显示对应内容。</p>}
        </div>
      </section>
    </div>
  );
}
