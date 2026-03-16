/** AgentOS API client — fetch + SSE + WebSocket handlers. */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

// ── Types ────────────────────────────────────────────────────────────────

export interface Task {
  id: string;
  goal: string;
  status: "queued" | "running" | "completed" | "cancelled" | "failed";
  model: string | null;
  config: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  artifacts: Artifact[] | null;
  estimated_cost: number;
  budget_limit: number | null;
  user_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Artifact {
  type: string;
  name: string;
  content_b64?: string;
  mime_type: string;
  format: string;
  url?: string;
}

export interface TaskEvent {
  type: "thought" | "action" | "result" | "error" | "status" | "artifact";
  content: string;
  agent?: string;
  timestamp: string;
  data?: Record<string, unknown>;
}

export interface CostEstimate {
  model: string;
  estimated_tokens: number;
  estimated_cost: number;
  breakdown: { input_cost: number; output_cost: number };
}

export interface CreateTaskPayload {
  goal: string;
  model?: string;
  budget_limit?: number;
  config?: Record<string, unknown>;
}

// ── HTTP client ──────────────────────────────────────────────────────────

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API error ${res.status}: ${text}`);
  }

  return res.json();
}

// ── Tasks ────────────────────────────────────────────────────────────────

export async function createTask(payload: CreateTaskPayload): Promise<Task> {
  return request<Task>("/tasks", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getTask(taskId: string): Promise<Task> {
  return request<Task>(`/tasks/${taskId}`);
}

export async function listTasks(page = 1, pageSize = 20): Promise<{ tasks: Task[]; total: number }> {
  return request(`/tasks?page=${page}&page_size=${pageSize}`);
}

export async function cancelTask(taskId: string): Promise<void> {
  await request(`/tasks/${taskId}`, { method: "DELETE" });
}

// ── Billing ──────────────────────────────────────────────────────────────

export async function estimateCost(
  goal: string,
  model?: string,
): Promise<CostEstimate> {
  return request<CostEstimate>("/billing/estimate", {
    method: "POST",
    body: JSON.stringify({ goal, model }),
  });
}

// ── Agents ───────────────────────────────────────────────────────────────

export interface AgentInfo {
  id: string;
  name: string;
  type: string;
  is_core: boolean;
}

export async function listAgents(): Promise<AgentInfo[]> {
  return request<AgentInfo[]>("/agents");
}

// ── SSE stream ───────────────────────────────────────────────────────────

export function subscribeToTask(
  taskId: string,
  onEvent: (event: TaskEvent) => void,
  onError?: (error: Error) => void,
): () => void {
  const url = `${API_BASE}/tasks/${taskId}/stream`;
  const eventSource = new EventSource(url);

  eventSource.onmessage = (e) => {
    try {
      const event: TaskEvent = JSON.parse(e.data);
      onEvent(event);
    } catch {
      // Non-JSON event, wrap as status
      onEvent({
        type: "status",
        content: e.data,
        timestamp: new Date().toISOString(),
      });
    }
  };

  eventSource.onerror = () => {
    onError?.(new Error("SSE connection lost"));
  };

  // Return cleanup function
  return () => eventSource.close();
}

// ── WebSocket (human-in-the-loop) ────────────────────────────────────────

export function connectTaskWebSocket(
  taskId: string,
  onMessage: (event: TaskEvent) => void,
  onError?: (error: Error) => void,
): { send: (msg: string) => void; close: () => void } {
  const ws = new WebSocket(`${WS_BASE}/ws/tasks/${taskId}`);

  ws.onmessage = (e) => {
    try {
      const event: TaskEvent = JSON.parse(e.data);
      onMessage(event);
    } catch {
      onMessage({
        type: "status",
        content: e.data,
        timestamp: new Date().toISOString(),
      });
    }
  };

  ws.onerror = () => onError?.(new Error("WebSocket error"));

  return {
    send: (msg: string) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "user_input", content: msg }));
      }
    },
    close: () => ws.close(),
  };
}
