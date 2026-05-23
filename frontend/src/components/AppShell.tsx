import {
  ChevronDown,
  LocateFixed,
  MapPin,
  Navigation2,
  Plus,
  Salad,
  Sparkles,
  type LucideIcon
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { createSession, getCities, runQuickAction } from "../api/streamClient";
import type { AppView } from "../App";

interface NavigationItem {
  id: AppView;
  label: string;
  icon: LucideIcon;
}

interface AppShellProps {
  activeView: AppView;
  navigation: readonly NavigationItem[];
  city: string;
  pageTitle: string;
  onCityChange: (city: string) => void;
  onNavigate: (view: AppView) => void;
  children: ReactNode;
}

const quickActions = [
  { id: "new", label: "新建规划", icon: Plus, tone: "purple" },
  { id: "nearby", label: "附近推荐", icon: LocateFixed, tone: "blue" },
  { id: "family", label: "亲子活动", icon: Sparkles, tone: "green" },
  { id: "restaurants", label: "低卡轻食", icon: Salad, tone: "orange" }
] as const;

export function AppShell({
  activeView,
  navigation,
  city,
  pageTitle,
  onCityChange,
  onNavigate,
  children
}: AppShellProps) {
  const [cities, setCities] = useState<Array<{ code: string; name: string; enabled: boolean }>>([
    { code: "beijing", name: "北京", enabled: true }
  ]);
  const [shellStatus, setShellStatus] = useState<string | null>(null);

  useEffect(() => {
    getCities()
      .then((result) => setCities(result.cities))
      .catch((error) => setShellStatus((error as Error).message));
  }, []);

  async function handleQuickAction(action: (typeof quickActions)[number]["id"]) {
    try {
      if (action === "new") {
        await createSession();
        setShellStatus("新的规划会话已准备好。");
      } else {
        const result = await runQuickAction(action);
        setShellStatus(`${result.action.title}预设已加载。`);
      }
      onNavigate("planner");
    } catch (error) {
      setShellStatus((error as Error).message);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <MapPin size={28} />
          </div>
          <div className="nav-label">
            <strong>生活路线</strong>
            <span>智能生活规划</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="主导航">
          {navigation.map((item) => {
            const Icon = item.icon;
            const isActive = activeView === item.id;
            return (
              <button
                key={item.id}
                className={`nav-item ${isActive ? "is-active" : ""}`}
                type="button"
                title={item.label}
                onClick={() => onNavigate(item.id)}
              >
                <Icon size={21} />
                <span className="nav-label">{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="quick-actions">
          <h2 className="nav-label">快捷入口</h2>
          <div className="quick-grid">
            {quickActions.map((action) => {
              const Icon = action.icon;
              return (
                <button
                  className="quick-tile"
                  data-tone={action.tone}
                  type="button"
                  key={action.label}
                  title={action.label}
                  onClick={() => void handleQuickAction(action.id)}
                >
                  <Icon size={19} />
                  <span className="nav-label">{action.label}</span>
                </button>
              );
            })}
          </div>
        </div>
      </aside>

      <main className="main-surface">
        <header className="topbar">
          <div>
            <h1>下午好，Jason</h1>
            <p>{pageTitle === "首页" ? "今天想去哪里玩？我来帮你规划。" : pageTitle}</p>
          </div>
          <div className="topbar-actions">
            {shellStatus && <span className="shell-status">{shellStatus}</span>}
            <label className="city-switcher">
              <MapPin size={16} />
              <select value={city} onChange={(event) => onCityChange(event.target.value)}>
                {cities.map((item) => (
                  <option key={item.code} value={item.code} disabled={!item.enabled}>
                    {item.name}
                  </option>
                ))}
              </select>
              <ChevronDown size={15} />
            </label>
            <div className="avatar-wrap">
              <div className="avatar" aria-hidden="true">
                J
              </div>
              <strong>Jason</strong>
              <Navigation2 size={15} />
            </div>
          </div>
        </header>
        {children}
      </main>
    </div>
  );
}
