import type { Health, InvestigationResponse, ToolSpec } from "./types";

// Base URL is configurable at build time (VITE_API_BASE_URL); default: same origin (nginx / vite proxy).
const BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit, timeoutMs = 90_000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = (body as { error?: { code?: string; message?: string } }).error;
      throw new ApiError(err?.message ?? `HTTP ${res.status}`, res.status, err?.code);
    }
    return body as T;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    if ((e as Error).name === "AbortError") throw new ApiError("The request timed out", 0, "TIMEOUT");
    throw new ApiError("Copilot backend is unreachable", 0, "NETWORK");
  } finally {
    clearTimeout(timer);
  }
}

export const api = {
  health: () => request<Health>("/api/health", undefined, 10_000),
  tools: () => request<{ server: string; url: string; tools: ToolSpec[] }>("/api/tools", undefined, 20_000),
  chat: (message: string, conversationId?: string) =>
    request<InvestigationResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({ message, conversation_id: conversationId }),
    }),
};
