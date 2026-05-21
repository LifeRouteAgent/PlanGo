import type { AdjustPlanResponse, DataSourceStatus, ExecutionStep, RankedPlan, TripPlanRequest, TripPlanResponse, TripPlanStreamEvent } from "../types";

// Local dev defaults to Vite's same-origin proxy so remote browsers do not
// resolve the backend loopback address on their own machine.
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

// 同步规划接口保留给调试和不支持流式读取的调用方。
export async function planTrip(request: TripPlanRequest): Promise<TripPlanResponse> {
  const response = await fetch(`${API_BASE_URL}/trip/plan`, {
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

export interface PlanTripStreamCallbacks {
  onEvent?: (event: TripPlanStreamEvent) => void;
  onChunk?: (delta: string) => void;
  onFinal?: (response: TripPlanResponse) => void;
}

export interface ExecutePlanStreamCallbacks {
  onStart?: (payload: Record<string, unknown>) => void;
  onStep?: (step: ExecutionStep) => void;
  onDone?: (payload: Record<string, unknown>) => void;
}

// 流式规划接口：后端使用 SSE 格式返回，但因为需要 POST 请求，这里用 fetch + ReadableStream 解析。
export async function planTripStream(
  request: TripPlanRequest,
  callbacks: PlanTripStreamCallbacks = {}
): Promise<TripPlanResponse> {
  const response = await fetch(`${API_BASE_URL}/trip/plan/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify(request)
  });

  if (!response.ok || !response.body) {
    const message = await response.text();
    throw new Error(`流式规划请求失败：${response.status} ${message}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finalResponse: TripPlanResponse | null = null;

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";

    for (const rawEvent of events) {
      const parsed = parseSseEvent(rawEvent);
      if (!parsed) {
        continue;
      }
      callbacks.onEvent?.(parsed);
      if (parsed.event === "response_chunk") {
        const delta = typeof parsed.data.delta === "string" ? parsed.data.delta : "";
        callbacks.onChunk?.(delta);
      }
      if (parsed.event === "final") {
        finalResponse = parsed.data as unknown as TripPlanResponse;
        callbacks.onFinal?.(finalResponse);
      }
    }
  }

  if (!finalResponse) {
    throw new Error("流式规划结束，但没有收到 final 响应。");
  }
  return finalResponse;
}

export async function executePlanStream(
  plan: RankedPlan,
  callbacks: ExecutePlanStreamCallbacks = {}
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/trip/execute/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify({ plan })
  });

  if (!response.ok || !response.body) {
    const message = await response.text();
    throw new Error(`执行方案失败：${response.status} ${message}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const rawEvent of events) {
      const parsed = parseSseEvent(rawEvent);
      if (!parsed) {
        continue;
      }
      if (parsed.event === "execution_start") {
        callbacks.onStart?.(parsed.data);
      }
      if (parsed.event === "execution_step") {
        callbacks.onStep?.(parsed.data as unknown as ExecutionStep);
      }
      if (parsed.event === "execution_done") {
        callbacks.onDone?.(parsed.data);
      }
    }
  }
}

export async function exportPlanPdf(plan: RankedPlan): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/export/plan/pdf`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ plan })
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`导出 PDF 失败：${response.status} ${message}`);
  }

  return await response.blob();
}

export async function adjustPlanPoi(plan: RankedPlan, poiId: string, prompt: string): Promise<AdjustPlanResponse> {
  const response = await fetch(`${API_BASE_URL}/trip/plan/adjust`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      plan,
      poi_id: poiId,
      prompt
    })
  });

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`局部调整失败：${response.status} ${message}`);
  }

  return (await response.json()) as AdjustPlanResponse;
}

// 解析最小 SSE 格式：event: xxx + data: {...}
function parseSseEvent(raw: string): TripPlanStreamEvent | null {
  const lines = raw.split(/\r?\n/);
  const eventLine = lines.find((line) => line.startsWith("event:"));
  const dataLine = lines.find((line) => line.startsWith("data:"));
  if (!eventLine || !dataLine) {
    return null;
  }

  const event = eventLine.replace(/^event:\s*/, "").trim();
  const dataText = dataLine.replace(/^data:\s*/, "");
  try {
    return {
      event,
      data: JSON.parse(dataText) as Record<string, unknown>
    };
  } catch {
    return null;
  }
}

// 数据源状态接口用于 review 和排障：它能明确告诉页面当前是否读取 MySQL。
export async function getDataSourceStatus(): Promise<DataSourceStatus> {
  const response = await fetch(`${API_BASE_URL}/trip/data-source`);

  if (!response.ok) {
    const message = await response.text();
    throw new Error(`数据源状态请求失败：${response.status} ${message}`);
  }

  return (await response.json()) as DataSourceStatus;
}
