import { Mic, RefreshCcw, SendHorizontal, Sparkles, Square } from "lucide-react";
import { startVoiceInput } from "../api/streamClient";

interface GoalComposerProps {
  goal: string;
  city: string;
  execute: boolean;
  failBooking: boolean;
  isRunning: boolean;
  onGoalChange: (goal: string) => void;
  onCityChange: (city: string) => void;
  onExecuteChange: (execute: boolean) => void;
  onFailBookingChange: (enabled: boolean) => void;
  onSubmit: () => void;
  onCancel: () => void;
}

const familyPrompt =
  "今天下午带 5 岁孩子在北京玩几个小时，别太远，晚饭想吃清淡低脂的。";

const friendsPrompt =
  "周末下午和 4 个朋友在北京轻松玩半天，适合聊天拍照，预算适中。";

export function GoalComposer({
  goal,
  city,
  execute,
  failBooking,
  isRunning,
  onGoalChange,
  onCityChange,
  onExecuteChange,
  onFailBookingChange,
  onSubmit,
  onCancel
}: GoalComposerProps) {
  async function handleVoiceInput() {
    await startVoiceInput();
  }

  return (
    <section className="plan-composer" aria-label="规划需求输入">
      <div className="composer-shell">
        <Sparkles className="composer-spark" size={20} aria-hidden="true" />
        <label className="sr-only" htmlFor="goal-input">
          规划需求
        </label>
        <textarea
          id="goal-input"
          value={goal}
          onChange={(event) => onGoalChange(event.target.value)}
          placeholder={familyPrompt}
          rows={2}
        />
        <button
          className="composer-icon-button"
          type="button"
          aria-label="语音输入"
          onClick={handleVoiceInput}
        >
          <Mic size={19} />
        </button>
        <button
          className="composer-send"
          type="button"
          onClick={isRunning ? onCancel : onSubmit}
          disabled={!goal.trim()}
          aria-label={isRunning ? "停止规划" : "生成方案"}
        >
          {isRunning ? <Square size={18} /> : <SendHorizontal size={19} />}
        </button>
      </div>

      <div className="composer-options">
        <label className="city-select">
          <span>城市</span>
          <select value={city} onChange={(event) => onCityChange(event.target.value)}>
            <option value="beijing">北京</option>
            <option value="shanghai" disabled>
              上海
            </option>
            <option value="hangzhou" disabled>
              杭州
            </option>
            <option value="shenzhen" disabled>
              深圳
            </option>
          </select>
        </label>
        <label className="toggle-pill">
          <input
            type="checkbox"
            checked={execute}
            onChange={(event) => onExecuteChange(event.target.checked)}
          />
          <span>生成后模拟预订</span>
        </label>
        <label className="toggle-pill">
          <input
            type="checkbox"
            checked={failBooking}
            onChange={(event) => onFailBookingChange(event.target.checked)}
          />
          <span>模拟餐厅预订失败</span>
        </label>
        <button
          className="sample-button"
          type="button"
          onClick={() => onGoalChange(familyPrompt)}
          disabled={isRunning}
        >
          <RefreshCcw size={15} />
          亲子示例
        </button>
        <button
          className="sample-button"
          type="button"
          onClick={() => onGoalChange(friendsPrompt)}
          disabled={isRunning}
        >
          朋友聚会
        </button>
      </div>
    </section>
  );
}
