"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Zap,
  CheckCircle2,
  XCircle,
  Info,
  Pause,
  Play,
  FileDown,
} from "lucide-react";
import { subscribeToTask, type TaskEvent } from "@/lib/api";

interface AgentStreamProps {
  taskId: string;
  onActiveAgent?: (agent: string) => void;
}

const EVENT_CONFIG: Record<
  string,
  { icon: typeof Brain; color: string; bg: string; label: string }
> = {
  thought: {
    icon: Brain,
    color: "text-accent-blue",
    bg: "bg-accent-blue/10",
    label: "Thought",
  },
  action: {
    icon: Zap,
    color: "text-accent-yellow",
    bg: "bg-accent-yellow/10",
    label: "Action",
  },
  result: {
    icon: CheckCircle2,
    color: "text-accent-green",
    bg: "bg-accent-green/10",
    label: "Result",
  },
  error: {
    icon: XCircle,
    color: "text-accent-red",
    bg: "bg-accent-red/10",
    label: "Error",
  },
  status: {
    icon: Info,
    color: "text-text-tertiary",
    bg: "bg-bg-hover",
    label: "Status",
  },
  artifact: {
    icon: FileDown,
    color: "text-accent-purple",
    bg: "bg-accent-purple/10",
    label: "Artifact",
  },
};

export function AgentStream({ taskId, onActiveAgent }: AgentStreamProps) {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const [connected, setConnected] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(false);

  pausedRef.current = paused;

  const handleEvent = useCallback(
    (event: TaskEvent) => {
      if (!pausedRef.current) {
        setEvents((prev) => [...prev, event]);
        if (event.agent) {
          onActiveAgent?.(event.agent);
        }
      }
    },
    [onActiveAgent],
  );

  useEffect(() => {
    setConnected(true);
    const unsubscribe = subscribeToTask(
      taskId,
      handleEvent,
      () => setConnected(false),
    );
    return unsubscribe;
  }, [taskId, handleEvent]);

  // Auto-scroll
  useEffect(() => {
    if (!paused && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events, paused]);

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-border">
        <div className="flex items-center gap-2.5">
          <h2 className="text-[13px] font-semibold">Agent Activity</h2>
          <div className="flex items-center gap-1.5">
            <span
              className={`w-1.5 h-1.5 rounded-full ${connected ? "bg-accent-green" : "bg-accent-red"}`}
            />
            <span className="text-[11px] text-text-tertiary font-mono">
              {connected ? "Live" : "Disconnected"}
            </span>
          </div>
        </div>
        <button
          onClick={() => setPaused(!paused)}
          className="flex items-center gap-1.5 h-7 px-2.5 rounded-md bg-bg-tertiary border border-border text-[11px] text-text-secondary hover:text-text-primary transition-colors"
        >
          {paused ? <Play className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
          {paused ? "Resume" : "Pause"}
        </button>
      </div>

      {/* Event timeline */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4">
        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-text-tertiary">
            <Brain className="w-8 h-8 mb-3 opacity-30" />
            <p className="text-[13px]">Waiting for agent activity...</p>
          </div>
        ) : (
          <div className="space-y-3">
            <AnimatePresence initial={false}>
              {events.map((event, i) => (
                <EventCard key={i} event={event} />
              ))}
            </AnimatePresence>
          </div>
        )}
      </div>

      {/* Event count */}
      <div className="px-5 py-2 border-t border-border">
        <span className="text-[11px] text-text-tertiary font-mono">
          {events.length} events
          {paused && " (paused)"}
        </span>
      </div>
    </div>
  );
}

function EventCard({ event }: { event: TaskEvent }) {
  const config = EVENT_CONFIG[event.type] || EVENT_CONFIG.status;
  const Icon = config.icon;
  const time = new Date(event.timestamp).toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, delay: 0.02 }}
      className={`rounded-xl border border-border ${config.bg} p-4`}
    >
      <div className="flex items-start gap-3">
        <div className={`mt-0.5 ${config.color}`}>
          <Icon className="w-4 h-4" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className={`text-[11px] font-semibold uppercase tracking-wider ${config.color}`}>
              {config.label}
            </span>
            {event.agent && (
              <span className="text-[10px] text-text-tertiary font-mono bg-bg-primary/50 px-1.5 py-0.5 rounded">
                {event.agent}
              </span>
            )}
            <span className="text-[10px] text-text-tertiary font-mono ml-auto">
              {time}
            </span>
          </div>
          <p className="text-[13px] text-text-secondary leading-relaxed whitespace-pre-wrap break-words">
            {event.content}
          </p>
        </div>
      </div>
    </motion.div>
  );
}
