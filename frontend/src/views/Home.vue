<script setup lang="ts">
import { computed, ref } from "vue";
import AmapTripMap from "../components/AmapTripMap.vue";
import { planTrip } from "../services/api";
import type { TripPlanResponse } from "../types";

// 默认输入覆盖“朋友 + 吃饭 + 电影 + 时间/预算约束”，用于快速验证 Gate 5。
const query = ref("周末和朋友出去玩 4 个小时，想吃饭看电影，预算 600 元");
const loading = ref(false);
const errorMessage = ref("");
const result = ref<TripPlanResponse | null>(null);

const hasPlan = computed(() => Boolean(result.value?.selected_plan?.id));

async function submitPlan() {
  errorMessage.value = "";
  loading.value = true;

  try {
    result.value = await planTrip({
      user_query: query.value,
      max_replanning_count: 2
    });
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "规划请求失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="workspace">
    <section class="composer">
      <div>
        <p class="eyebrow">LifeRouteAgent</p>
        <h1>本地生活周末规划</h1>
        <p class="intro">输入自然语言需求，后端 LangGraph DAG 会返回模拟方案、日志和异常状态。</p>
      </div>

      <label class="query-box">
        <span>用户需求</span>
        <textarea v-model="query" rows="5" />
      </label>

      <button :disabled="loading || !query.trim()" @click="submitPlan">
        {{ loading ? "规划中..." : "生成行程" }}
      </button>

      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
    </section>

    <section class="result-grid">
      <article class="panel plan-panel">
        <div class="panel-header">
          <h2>方案结果</h2>
          <span v-if="result">{{ result.execution_status }}</span>
        </div>

        <pre v-if="result?.response_text" class="response">{{ result.response_text }}</pre>
        <p v-else class="empty">还没有生成方案。</p>

        <div v-if="result?.errors.length" class="issues">
          <strong>错误状态</strong>
          <ul>
            <li v-for="item in result.errors" :key="item">{{ item }}</li>
          </ul>
        </div>
      </article>

      <article class="panel">
        <div class="panel-header">
          <h2>地图与时间线</h2>
        </div>
        <AmapTripMap v-if="hasPlan && result" :plan="result.selected_plan" />
        <p v-else class="empty">生成方案后展示路线占位和时间线。</p>
      </article>

      <article class="panel logs-panel">
        <div class="panel-header">
          <h2>DAG 日志</h2>
          <span>{{ result?.logs.length ?? 0 }} 条</span>
        </div>
        <ol v-if="result?.logs.length">
          <li v-for="log in result.logs" :key="log">{{ log }}</li>
        </ol>
        <p v-else class="empty">等待后端返回节点日志。</p>
      </article>
    </section>
  </main>
</template>

<style scoped>
.workspace {
  display: grid;
  grid-template-columns: minmax(300px, 420px) 1fr;
  gap: 24px;
  min-height: 100vh;
  padding: 28px;
  background: #eef2f7;
  color: #162033;
}

.composer,
.panel {
  border: 1px solid #d8dee8;
  border-radius: 8px;
  background: white;
  box-shadow: 0 10px 30px rgb(23 32 51 / 8%);
}

.composer {
  display: flex;
  flex-direction: column;
  gap: 20px;
  align-self: start;
  padding: 24px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #1f6feb;
  font-size: 13px;
  font-weight: 700;
}

h1,
h2,
p {
  margin-top: 0;
}

h1 {
  margin-bottom: 12px;
  font-size: 28px;
}

h2 {
  margin-bottom: 0;
  font-size: 18px;
}

.intro {
  margin-bottom: 0;
  color: #687386;
  line-height: 1.6;
}

.query-box {
  display: grid;
  gap: 8px;
  color: #344052;
  font-weight: 700;
}

textarea {
  width: 100%;
  box-sizing: border-box;
  resize: vertical;
  border: 1px solid #c8d1df;
  border-radius: 8px;
  padding: 12px;
  color: #162033;
  font: inherit;
  line-height: 1.6;
}

button {
  border: 0;
  border-radius: 8px;
  padding: 12px 16px;
  background: #1f6feb;
  color: white;
  font: inherit;
  font-weight: 700;
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.error {
  margin-bottom: 0;
  color: #b42318;
}

.result-grid {
  display: grid;
  grid-template-columns: minmax(320px, 1fr) minmax(320px, 1fr);
  gap: 20px;
}

.panel {
  padding: 20px;
}

.plan-panel,
.logs-panel {
  grid-column: span 1;
}

.logs-panel {
  grid-column: 1 / -1;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
}

.panel-header span {
  border-radius: 999px;
  background: #eef4ff;
  color: #1f6feb;
  padding: 4px 10px;
  font-size: 12px;
  font-weight: 700;
}

.response {
  white-space: pre-wrap;
  margin: 0;
  color: #263246;
  font-family: inherit;
  line-height: 1.7;
}

.empty {
  margin-bottom: 0;
  color: #687386;
}

.issues {
  margin-top: 20px;
  border-top: 1px solid #e4e9f1;
  padding-top: 16px;
}

.issues ul,
.logs-panel ol {
  margin-bottom: 0;
  padding-left: 20px;
}

.logs-panel li {
  margin-bottom: 8px;
  color: #344052;
}

@media (max-width: 920px) {
  .workspace,
  .result-grid {
    grid-template-columns: 1fr;
  }

  .logs-panel {
    grid-column: auto;
  }
}
</style>
