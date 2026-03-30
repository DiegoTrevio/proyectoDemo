"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { motion } from "framer-motion";
import {
  Clock,
  CheckCircle2,
  XCircle,
  Loader2,
  ListTodo,
  Activity,
  DollarSign,
  Bot,
  Heart,
  Zap,
  Settings,
  ChevronDown,
  ChevronUp,
  RefreshCw,
} from "lucide-react";
import { TaskInput } from "@/components/TaskInput";
import {
  createTask,
  listTasks,
  loadApiKey,
  setApiKey,
  clearApiKey,
  hasSession,
  signOut,
  ApiError,
  getAgentsHealth,
  listSkills,
  reloadSkills,
  type Task,
} from "@/lib/api";

const STATUS_CONFIG: Record<
  string,
  { icon: typeof Clock; color: string; bg: string; label: string }
> = {
  queued: { icon: Clock, color: "text-text-tertiary", bg: "bg-bg-hover", label: "Queued" },
  running: { icon: Loader2, color: "text-accent-blue", bg: "bg-accent-blue/10", label: "Running" },
  completed: { icon: CheckCircle2, color: "text-accent-green", bg: "bg-accent-green/10", label: "Completed" },
  failed: { icon: XCircle, color: "text-accent-red", bg: "bg-accent-red/10", label: "Failed" },
  cancelled: { icon: XCircle, color: "text-text-tertiary", bg: "bg-bg-hover", label: "Cancelled" },
};

export default function Dashboard() {
  const router = useRouter();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [needsAuth, setNeedsAuth] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [authMethod, setAuthMethod] = useState<"session" | "apikey" | null>(null);
  const [showTaskInput, setShowTaskInput] = useState(false);
  const [agentHealth, setAgentHealth] = useState<Record<string, string>>({});
  const [skillCount, setSkillCount] = useState(0);
  const [reloading, setReloading] = useState(false);

  useEffect(() => {
    async function checkAuth() {
      if (await hasSession()) {
        setAuthMethod("session");
        setNeedsAuth(false);
        return;
      }
      const key = loadApiKey();
      if (key) {
        setAuthMethod("apikey");
        setNeedsAuth(false);
        return;
      }
      setNeedsAuth(true);
    }
    checkAuth();
  }, []);

  const handleLogin = () => {
    if (apiKeyInput.trim()) {
      setApiKey(apiKeyInput.trim());
      setAuthMethod("apikey");
      setNeedsAuth(false);
      setError(null);
      fetchData();
    }
  };

  const handleLogout = async () => {
    if (authMethod === "session") {
      await signOut();
    }
    clearApiKey();
    setAuthMethod(null);
    setNeedsAuth(true);
    setTasks([]);
  };

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [taskData, health, skills] = await Promise.all([
        listTasks(1, 20).catch(() => ({ tasks: [], total: 0 })),
        getAgentsHealth().catch(() => ({})),
        listSkills().catch(() => []),
      ]);
      setTasks(taskData.tasks || []);
      setAgentHealth(health);
      setSkillCount(skills.length);
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        setNeedsAuth(true);
        setError("API key is invalid or expired.");
      } else {
        setError("Cannot connect to AgentOS backend. Is the server running?");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!needsAuth) fetchData();
  }, [fetchData, needsAuth]);

  const handleSubmit = async (goal: string, model: string, budgetLimit: number) => {
    setSubmitting(true);
    setError(null);
    try {
      const task = await createTask({
        goal,
        model: model !== "auto" ? model : undefined,
        budget_limit: budgetLimit,
      });
      router.push(`/task/${task.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.isUnauthorized) {
        setNeedsAuth(true);
        setError("Session expired. Please log in again.");
      } else {
        setError("Failed to create task.");
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleReloadSkills = async () => {
    setReloading(true);
    try {
      const result = await reloadSkills();
      setSkillCount(result.loaded);
    } catch {
      // silent
    } finally {
      setReloading(false);
    }
  };

  // Auth screen
  if (needsAuth) {
    return (
      <div className="max-w-md mx-auto px-6 py-24">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold tracking-tight mb-2">Welcome to AgentOS</h1>
          <p className="text-[13px] text-text-secondary">Sign in to get started.</p>
        </div>
        {error && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-accent-red/10 border border-accent-red/20 text-[13px] text-accent-red">
            {error}
          </div>
        )}
        <div className="space-y-4">
          <a
            href="/auth"
            className="block w-full px-4 py-3 rounded-xl bg-accent-blue text-white text-[13px] font-medium text-center hover:bg-accent-blue/90 transition-colors"
          >
            Sign in with Email
          </a>
          <div className="flex items-center gap-3">
            <div className="flex-1 h-px bg-border" />
            <span className="text-[11px] text-text-tertiary uppercase tracking-wider">or use API key</span>
            <div className="flex-1 h-px bg-border" />
          </div>
          <input
            type="password"
            value={apiKeyInput}
            onChange={(e) => setApiKeyInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleLogin()}
            placeholder="sa_live_..."
            className="w-full px-4 py-3 rounded-xl border border-border bg-bg-card text-[13px] font-mono placeholder:text-text-tertiary focus:outline-none focus:border-accent-blue"
          />
          <button
            onClick={handleLogin}
            disabled={!apiKeyInput.trim()}
            className="w-full px-4 py-3 rounded-xl border border-border bg-bg-card text-[13px] font-medium text-text-secondary hover:bg-bg-hover transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Connect with API Key
          </button>
        </div>
      </div>
    );
  }

  const agentNames = Object.keys(agentHealth);
  const agentsOnline = agentNames.filter(
    (n) => agentHealth[n] === "real" || agentHealth[n] === "available"
  ).length;

  const stats = {
    total: tasks.length,
    running: tasks.filter((t) => t.status === "running").length,
    totalCost: tasks.reduce((acc, t) => acc + (t.estimated_cost || 0), 0),
  };

  return (
    <div className="max-w-[1400px] mx-auto px-6 py-8">
      {/* Error banner */}
      {error && (
        <motion.div
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="mb-6 px-4 py-3 rounded-lg bg-accent-red/10 border border-accent-red/20 flex items-center justify-between"
        >
          <span className="text-[13px] text-accent-red">{error}</span>
          <button onClick={() => setError(null)} className="text-accent-red/60 hover:text-accent-red text-sm ml-4">
            Dismiss
          </button>
        </motion.div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-[13px] text-text-secondary mt-0.5">Operations overview</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowTaskInput(!showTaskInput)}
            className="px-4 py-2 text-[13px] font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors flex items-center gap-1.5"
          >
            <Zap className="w-3.5 h-3.5" />
            New Task
            {showTaskInput ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          <button
            onClick={handleLogout}
            className="px-3 py-2 text-[12px] text-text-tertiary hover:text-text-secondary transition-colors"
          >
            Logout
          </button>
        </div>
      </div>

      {/* Task Input (collapsible) */}
      {showTaskInput && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          exit={{ opacity: 0, height: 0 }}
          className="mb-6"
        >
          <TaskInput onSubmit={handleSubmit} loading={submitting} />
        </motion.div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-6">
        {[
          { icon: ListTodo, label: "Total Tasks", value: stats.total.toString(), color: "text-accent-blue" },
          { icon: Activity, label: "Running", value: stats.running.toString(), color: "text-accent-green" },
          { icon: DollarSign, label: "Cost", value: `$${stats.totalCost.toFixed(2)}`, color: "text-accent-yellow" },
          {
            icon: Bot,
            label: "Agents",
            value: agentNames.length > 0 ? `${agentsOnline}/${agentNames.length}` : "-",
            color: agentsOnline === agentNames.length ? "text-accent-green" : "text-accent-yellow",
          },
        ].map((stat) => (
          <motion.div
            key={stat.label}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-xl border border-border bg-bg-card p-4"
          >
            <div className="flex items-center gap-2 mb-1.5">
              <stat.icon className={`w-3.5 h-3.5 ${stat.color}`} />
              <span className="text-[10px] text-text-tertiary uppercase tracking-wider font-medium">
                {stat.label}
              </span>
            </div>
            <span className="text-xl font-semibold font-mono">{stat.value}</span>
          </motion.div>
        ))}
      </div>

      {/* Two-column: Health + Quick Actions */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        {/* System Health */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.05 }}
          className="lg:col-span-2 rounded-xl border border-border bg-bg-card p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Heart className="w-4 h-4 text-accent-green" />
            <h2 className="text-[13px] font-semibold">System Health</h2>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {agentNames.length > 0 ? (
              agentNames.map((name) => {
                const status = agentHealth[name];
                const isUp = status === "real" || status === "available";
                return (
                  <div
                    key={name}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg bg-bg-hover"
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${isUp ? "bg-accent-green" : "bg-accent-red"}`} />
                    <span className="text-[12px] capitalize truncate">{name.replace(/_/g, " ")}</span>
                  </div>
                );
              })
            ) : (
              <p className="text-[12px] text-text-tertiary col-span-3">Loading health data...</p>
            )}
          </div>
        </motion.div>

        {/* Quick Actions */}
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="rounded-xl border border-border bg-bg-card p-5"
        >
          <div className="flex items-center gap-2 mb-4">
            <Zap className="w-4 h-4 text-accent-yellow" />
            <h2 className="text-[13px] font-semibold">Quick Actions</h2>
          </div>
          <div className="space-y-1.5">
            <button
              onClick={() => setShowTaskInput(true)}
              className="w-full text-left px-3 py-2 rounded-lg text-[12px] hover:bg-bg-hover transition-colors flex items-center gap-2"
            >
              <Zap className="w-3 h-3 text-accent-blue" /> Create Task
            </button>
            <button
              onClick={() => router.push("/config")}
              className="w-full text-left px-3 py-2 rounded-lg text-[12px] hover:bg-bg-hover transition-colors flex items-center gap-2"
            >
              <Settings className="w-3 h-3 text-accent-purple" /> Manage Skills
              <span className="ml-auto text-[10px] text-text-tertiary font-mono">{skillCount}</span>
            </button>
            <button
              onClick={() => router.push("/agents")}
              className="w-full text-left px-3 py-2 rounded-lg text-[12px] hover:bg-bg-hover transition-colors flex items-center gap-2"
            >
              <Bot className="w-3 h-3 text-accent-green" /> View Agents
            </button>
            <button
              onClick={handleReloadSkills}
              disabled={reloading}
              className="w-full text-left px-3 py-2 rounded-lg text-[12px] hover:bg-bg-hover transition-colors flex items-center gap-2 disabled:opacity-50"
            >
              <RefreshCw className={`w-3 h-3 text-accent-yellow ${reloading ? "animate-spin" : ""}`} /> Reload Skills
            </button>
            <button
              onClick={fetchData}
              className="w-full text-left px-3 py-2 rounded-lg text-[12px] hover:bg-bg-hover transition-colors flex items-center gap-2"
            >
              <RefreshCw className="w-3 h-3 text-text-tertiary" /> Refresh
            </button>
          </div>
        </motion.div>
      </div>

      {/* Recent Tasks */}
      <div>
        <h2 className="text-[13px] font-semibold mb-3">Recent Tasks</h2>
        {loading ? (
          <div className="flex items-center justify-center py-12 text-text-tertiary">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            <span className="text-[13px]">Loading...</span>
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-12 text-text-tertiary">
            <ListTodo className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p className="text-[13px]">No tasks yet. Click &quot;New Task&quot; to create one.</p>
          </div>
        ) : (
          <div className="space-y-2">
            {tasks.map((task, i) => (
              <TaskRow key={task.id} task={task} index={i} onClick={() => router.push(`/task/${task.id}`)} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TaskRow({ task, index, onClick }: { task: Task; index: number; onClick: () => void }) {
  const config = STATUS_CONFIG[task.status] || STATUS_CONFIG.queued;
  const Icon = config.icon;
  const time = new Date(task.created_at).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  return (
    <motion.button
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03 }}
      onClick={onClick}
      className="w-full text-left flex items-center gap-4 px-5 py-4 rounded-xl border border-border bg-bg-card hover:border-border-hover hover:bg-bg-hover transition-colors group"
    >
      <div className={`w-8 h-8 rounded-lg ${config.bg} flex items-center justify-center flex-shrink-0`}>
        <Icon className={`w-4 h-4 ${config.color} ${task.status === "running" ? "animate-spin" : ""}`} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-[13px] font-medium text-text-primary truncate group-hover:text-white transition-colors">
          {task.goal}
        </p>
        <p className="text-[11px] text-text-tertiary font-mono mt-0.5">
          {time} {task.model && `\u00B7 ${task.model.replace("agentOS/", "")}`}
        </p>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0">
        {task.estimated_cost > 0 && (
          <span className="text-[11px] text-text-tertiary font-mono">
            ${task.estimated_cost.toFixed(3)}
          </span>
        )}
        <span className={`text-[11px] font-medium ${config.color} ${config.bg} px-2 py-0.5 rounded-md`}>
          {config.label}
        </span>
      </div>
    </motion.button>
  );
}
