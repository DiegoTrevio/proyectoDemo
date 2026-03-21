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
} from "lucide-react";
import { TaskInput } from "@/components/TaskInput";
import { createTask, listTasks, loadApiKey, setApiKey, clearApiKey, ApiError, type Task } from "@/lib/api";

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

  // Load API key from localStorage on mount
  useEffect(() => {
    const key = loadApiKey();
    if (!key) {
      setNeedsAuth(true);
    }
  }, []);

  const handleLogin = () => {
    if (apiKeyInput.trim()) {
      setApiKey(apiKeyInput.trim());
      setNeedsAuth(false);
      setError(null);
      fetchTasks();
    }
  };

  const handleLogout = () => {
    clearApiKey();
    setNeedsAuth(true);
    setTasks([]);
  };

  const fetchTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listTasks(1, 20);
      setTasks(data.tasks || []);
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.isUnauthorized) {
          setNeedsAuth(true);
          setError("API key is invalid or expired. Please enter a valid key.");
        } else if (err.isRateLimited) {
          setError("Rate limit exceeded. Please wait a moment and try again.");
        } else {
          setError(`API error: ${err.message}`);
        }
      } else {
        setError("Cannot connect to AgentOS backend. Is the server running?");
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!needsAuth) {
      fetchTasks();
    }
  }, [fetchTasks, needsAuth]);

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
      if (err instanceof ApiError) {
        if (err.isUnauthorized) {
          setNeedsAuth(true);
          setError("Session expired. Please log in again.");
        } else {
          setError(`Failed to create task: ${err.message}`);
        }
      } else {
        setError("Cannot connect to AgentOS backend. Is the server running?");
      }
    } finally {
      setSubmitting(false);
    }
  };

  // ── Auth screen ──
  if (needsAuth) {
    return (
      <div className="max-w-md mx-auto px-6 py-24">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold tracking-tight mb-2">Welcome to AgentOS</h1>
          <p className="text-[13px] text-text-secondary">Enter your API key to get started.</p>
        </div>
        {error && (
          <div className="mb-4 px-4 py-3 rounded-lg bg-accent-red/10 border border-accent-red/20 text-[13px] text-accent-red">
            {error}
          </div>
        )}
        <div className="space-y-3">
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
            className="w-full px-4 py-3 rounded-xl bg-accent-blue text-white text-[13px] font-medium hover:bg-accent-blue/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Connect
          </button>
        </div>
      </div>
    );
  }

  const stats = {
    total: tasks.length,
    running: tasks.filter((t) => t.status === "running").length,
    totalCost: tasks.reduce((acc, t) => acc + (t.estimated_cost || 0), 0),
  };

  return (
    <div className="max-w-[1400px] mx-auto px-6 py-12">
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

      {/* Hero section */}
      <div className="text-center mb-12">
        <motion.h1
          initial={{ opacity: 0, y: -10 }}
          animate={{ opacity: 1, y: 0 }}
          className="text-3xl font-bold tracking-tight mb-3"
        >
          What do you want to build?
        </motion.h1>
        <motion.p
          initial={{ opacity: 0, y: -5 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.1 }}
          className="text-[15px] text-text-secondary max-w-lg mx-auto"
        >
          Describe your task and AgentOS will orchestrate the right AI agents to get it done.
        </motion.p>
      </div>

      {/* Task input */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.2 }}
        className="mb-16"
      >
        <TaskInput onSubmit={handleSubmit} loading={submitting} />
      </motion.div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {[
          { icon: ListTodo, label: "Total Tasks", value: stats.total.toString(), color: "text-accent-blue" },
          { icon: Activity, label: "Running", value: stats.running.toString(), color: "text-accent-green" },
          { icon: DollarSign, label: "Total Cost", value: `$${stats.totalCost.toFixed(2)}`, color: "text-accent-yellow" },
        ].map((stat) => (
          <div
            key={stat.label}
            className="rounded-xl border border-border bg-bg-card p-5"
          >
            <div className="flex items-center gap-2 mb-2">
              <stat.icon className={`w-4 h-4 ${stat.color}`} />
              <span className="text-[11px] text-text-tertiary uppercase tracking-wider font-medium">
                {stat.label}
              </span>
            </div>
            <span className="text-2xl font-semibold font-mono">{stat.value}</span>
          </div>
        ))}
      </div>

      {/* Recent tasks */}
      <div>
        <h2 className="text-[13px] font-semibold mb-4">Recent Tasks</h2>
        {loading ? (
          <div className="flex items-center justify-center py-12 text-text-tertiary">
            <Loader2 className="w-5 h-5 animate-spin mr-2" />
            <span className="text-[13px]">Loading tasks...</span>
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-16 text-text-tertiary">
            <ListTodo className="w-8 h-8 mx-auto mb-3 opacity-30" />
            <p className="text-[13px]">No tasks yet. Create one above.</p>
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
