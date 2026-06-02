import type { Plan } from "../types/agent";

export interface StoredChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
}

export interface ConversationRecord {
  id: string;
  title: string;
  messages: StoredChatMessage[];
  plan: Plan | null;
  createdAt: string;
  updatedAt: string;
}

const CONVERSATIONS_KEY = "plango_conversations";
const ACTIVE_CONVERSATION_KEY = "plango_active_conversation_id";

export function welcomeMessage(): StoredChatMessage {
  return {
    id: "welcome",
    role: "assistant",
    content: "你好，我是 PlanGo。告诉我出行人数、时间、预算和偏好，我会帮你生成路线、行程和可执行操作。"
  };
}

export function createEmptyConversation(): ConversationRecord {
  const now = new Date().toISOString();
  return {
    id: crypto.randomUUID(),
    title: "新的对话",
    messages: [welcomeMessage()],
    plan: null,
    createdAt: now,
    updatedAt: now
  };
}

export function loadConversations(): ConversationRecord[] {
  try {
    const raw = window.localStorage.getItem(CONVERSATIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as ConversationRecord[];
    return Array.isArray(parsed) ? parsed.filter(isConversationRecord) : [];
  } catch {
    return [];
  }
}

export function saveConversations(records: ConversationRecord[]) {
  window.localStorage.setItem(CONVERSATIONS_KEY, JSON.stringify(records));
}

export function getActiveConversationId() {
  return window.localStorage.getItem(ACTIVE_CONVERSATION_KEY) || "";
}

export function setActiveConversationId(id: string) {
  window.localStorage.setItem(ACTIVE_CONVERSATION_KEY, id);
}

export function upsertConversation(record: ConversationRecord) {
  const records = loadConversations();
  const index = records.findIndex((item) => item.id === record.id);
  const nextRecord = {
    ...record,
    title: titleFromMessages(record.messages),
    updatedAt: new Date().toISOString()
  };
  const nextRecords =
    index >= 0
      ? records.map((item) => (item.id === record.id ? nextRecord : item))
      : [nextRecord, ...records];
  saveConversations(nextRecords.slice(0, 20));
  setActiveConversationId(nextRecord.id);
  return nextRecord;
}

export function loadOrCreateActiveConversation() {
  const records = loadConversations();
  const activeId = getActiveConversationId();
  const active = records.find((record) => record.id === activeId) ?? records[0];
  if (active) {
    setActiveConversationId(active.id);
    return active;
  }
  const created = createEmptyConversation();
  upsertConversation(created);
  return created;
}

export function titleFromMessages(messages: StoredChatMessage[]) {
  const firstUserMessage = messages.find((message) => message.role === "user" && message.content.trim());
  if (!firstUserMessage) return "新的对话";
  const text = firstUserMessage.content.replace(/\s+/g, " ").trim();
  return text.length > 24 ? `${text.slice(0, 24)}...` : text;
}

function isConversationRecord(value: ConversationRecord) {
  return Boolean(
    value &&
      typeof value.id === "string" &&
      Array.isArray(value.messages) &&
      typeof value.createdAt === "string" &&
      typeof value.updatedAt === "string"
  );
}
