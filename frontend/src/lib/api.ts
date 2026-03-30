/** AgentOS API client — fetch + SSE + WebSocket handlers. */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api/v1";
const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";

// ── Auth ─────────────────────────────────────────────────────────────────

let _apiKey: string | null = null;

/** Set the API key for all subsequent requests. */
export function setApiKey(key: string) {
  _apiKey = key;
  if (typeof window !== "undefined") {
    localStorage.setItem("agentos_api_key", key);
  }
}

/** Load API key from localStorage on init. */
export function loadApiKey(): string | null {
  if (typeof window !== "undefined") {
    _apiKey = localStorage.getItem("agentos_api_key");
  }
  return _apiKey;
}

/** Clear stored API key. */
export function clearApiKey() {
  _apiKey = null;
  if (typeof window !== "undefined") {
    localStorage.removeItem("agentos_api_key");
  }
}

/** Check if user has an active SuperTokens session. */
export async function hasSession(): Promise<boolean> {
  try {
    const Session = await import("supertokens-auth-react/recipe/session");
    return await Session.doesSessionExist();
  } catch {
    return false;
  }
}

/** Sign out from SuperTokens session. */
export async function signOut(): Promise<void> {
  try {
    const Session = await import("supertokens-auth-react/recipe/session");
    await Session.signOut();
  } catch {
    // SuperTokens not available
  }
}

function _authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {};
  if (_apiKey) {
    headers["Authorization"] = `Bearer ${_apiKey}`;
  }
  return headers;
}

/** Custom error class for API errors with status codes. */
export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }

  get isUnauthorized() {
    return this.status === 401;
  }

  get isRateLimited() {
    return this.status === 429;
  }
}

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
  type: "thought" | "action" | "result" | "error" | "status" | "artifact" | "approval_required";
  content: string;
  agent?: string;
  timestamp: string;
  data?: Record<string, unknown>;
  approval_id?: string;
  risk_level?: string;
  params?: Record<string, string>;
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
    credentials: "include", // Send SuperTokens session cookies automatically
    headers: {
      "Content-Type": "application/json",
      ..._authHeaders(),
      ...options?.headers,
    },
    ...options,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new ApiError(res.status, text || `HTTP ${res.status}`);
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

export interface UsageData {
  plan: string;
  tasks_used: number;
  tasks_limit: number;
  cost_this_month: number;
}

export async function getUsage(): Promise<UsageData> {
  return request<UsageData>("/billing/usage");
}

export async function createCheckoutSession(planId: string): Promise<{ url: string }> {
  return request<{ url: string }>("/billing/create-checkout-session", {
    method: "POST",
    body: JSON.stringify({ plan_id: planId }),
  });
}

export async function getPortalUrl(): Promise<{ url: string }> {
  return request<{ url: string }>("/billing/portal");
}

// ── API Keys ────────────────────────────────────────────────────────────

export interface ApiKeyInfo {
  id: string;
  key_prefix: string;
  name: string;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
  expires_at: string | null;
}

export async function listApiKeys(): Promise<ApiKeyInfo[]> {
  return request<ApiKeyInfo[]>("/keys");
}

export async function createApiKey(name: string): Promise<{ key: string; id: string }> {
  return request<{ key: string; id: string }>("/keys", {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function revokeApiKey(keyId: string): Promise<void> {
  await request(`/keys/${keyId}`, { method: "DELETE" });
}

// ── Agents ───────────────────────────────────────────────────────────────

export interface AgentInfo {
  agent_id: string;
  name: string;
  type: string;
  system_prompt?: string;
  tools: string[];
  model?: string;
  created_at: string;
}

export async function listAgents(): Promise<AgentInfo[]> {
  return request<AgentInfo[]>("/agents");
}

export async function getAgentsHealth(): Promise<Record<string, string>> {
  return request<Record<string, string>>("/agents/health");
}

export async function getDeerflowStatus(): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/agents/deerflow/status");
}

// ── Skills ──────────────────────────────────────────────────────────────

export interface SkillInfo {
  name: string;
  description: string;
  version: string;
  agents: string[];
  complexity_hint: string;
  tags: string[];
  trigger_count: number;
}

export interface SkillDetail {
  name: string;
  description: string;
  version: string;
  agents: string[];
  triggers: string[];
  task_types: string[];
  instructions: string;
  tools: string[];
  complexity_hint: string;
  tags: string[];
}

export interface SkillMatchResult {
  skill: string;
  confidence: number;
  matched_triggers: string[];
  agents: string[];
  description: string;
}

export interface SkillTestResult {
  valid: boolean;
  errors: { field: string; message: string }[];
  warnings: { field: string; message: string }[];
  matches: { goal: string; matched: boolean; confidence: number; matched_triggers: string[] }[];
}

export async function listSkills(): Promise<SkillInfo[]> {
  return request<SkillInfo[]>("/skills");
}

export async function getSkill(name: string): Promise<SkillDetail> {
  return request<SkillDetail>(`/skills/${name}`);
}

export async function createSkill(data: Record<string, unknown>): Promise<{ status: string; skill: string; warnings: { field: string; message: string }[] }> {
  return request("/skills", { method: "POST", body: JSON.stringify(data) });
}

export async function deleteSkill(name: string): Promise<void> {
  await request(`/skills/${name}`, { method: "DELETE" });
}

export async function testSkill(skill: Record<string, unknown>, sampleGoals: string[]): Promise<SkillTestResult> {
  return request<SkillTestResult>("/skills/test", {
    method: "POST",
    body: JSON.stringify({ skill, sample_goals: sampleGoals }),
  });
}

export async function reloadSkills(): Promise<{ loaded: number; added: string[]; removed: string[] }> {
  return request("/skills/reload", { method: "POST" });
}

export async function matchSkills(goal: string): Promise<SkillMatchResult[]> {
  return request<SkillMatchResult[]>(`/skills/match?goal=${encodeURIComponent(goal)}`);
}

export async function getSkillTemplate(name = "my-skill"): Promise<{ yaml: string }> {
  return request<{ yaml: string }>(`/skills/template?name=${encodeURIComponent(name)}`);
}

// ── Project Context ─────────────────────────────────────────────────────

export interface ProjectSection {
  section: string;
  content: string;
  updated_at?: string;
}

export interface DriftReport {
  score: number;
  healthy: boolean;
  issues: { severity: string; code: string; message: string; section?: string }[];
  checked_at: string;
}

export async function getProjectSections(): Promise<ProjectSection[]> {
  return request<ProjectSection[]>("/project/sections");
}

export async function getProjectDrift(): Promise<DriftReport> {
  return request<DriftReport>("/project/drift");
}

export async function updateProjectSection(section: string, content: string): Promise<void> {
  await request("/project/sections", {
    method: "POST",
    body: JSON.stringify({ section, content }),
  });
}

// ── Health ───────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<{ status: string }> {
  return request<{ status: string }>("");
}

// ── SSE stream ───────────────────────────────────────────────────────────

export function subscribeToTask(
  taskId: string,
  onEvent: (event: TaskEvent) => void,
  onError?: (error: Error) => void,
): () => void {
  const url = `${API_BASE}/tasks/${taskId}/stream`;
  const eventSource = new EventSource(url, { withCredentials: true });

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
