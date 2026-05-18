import type { DataSourceStatus, TripPlanRequest, TripPlanResponse } from "../types";

// 后端当前暴露的是同步规划接口。后续如果改成 SSE/任务轮询，
// 只需要替换这一层，页面组件不直接关心传输协议。
export async function planTrip(request: TripPlanRequest): Promise<TripPlanResponse> {
  const response = await fetch("/trip/plan", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(request)
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`规划请求失败：${response.status} ${message}`);
  }

  return (await response.json()) as TripPlanResponse;
}

// 数据源状态接口用于 review 和排障：它能明确告诉页面当前是否读取 MySQL。
export async function getDataSourceStatus(): Promise<DataSourceStatus> {
  const response = await fetch("/trip/data-source");

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`数据源状态请求失败：${response.status} ${message}`);
  }

  return (await response.json()) as DataSourceStatus;
}
