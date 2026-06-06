import type { Plan } from "../types/agent";
import { createId } from "./id";

export interface StoredChatMessage {
  id: string;
  role: "assistant" | "user";
  content: string;
}

export const PLAN_LINK_MESSAGE = "__PLANGO_PLAN_LINK__";

export function isPlanLinkMessage(message: StoredChatMessage) {
  return message.role === "assistant" && message.content === PLAN_LINK_MESSAGE;
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
    content: "**Hi，我是 PlanGo 👋**\n\n今天想和谁一起去出行？有什么想法告诉我吧~"
  };
}

export function createEmptyConversation(): ConversationRecord {
  const now = new Date().toISOString();
  return {
    id: createId(),
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

export function upsertConversation(record: ConversationRecord, options: { activate?: boolean } = {}) {
  const activate = options.activate ?? true;
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
  if (activate) {
    setActiveConversationId(nextRecord.id);
  }
  return nextRecord;
}

export function deleteConversation(conversationId: string) {
  const nextRecords = loadConversations().filter((record) => record.id !== conversationId);
  saveConversations(nextRecords);
  if (getActiveConversationId() === conversationId) {
    setActiveConversationId(nextRecords[0]?.id ?? "");
  }
  return nextRecords;
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
