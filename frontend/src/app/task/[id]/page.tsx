"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams } from "next/navigation";
import { ArrowLeft, Clock, DollarSign } from "lucide-react";
import { AgentStream } from "@/components/AgentStream";
import { WorkflowGraph } from "@/components/WorkflowGraph";
import { ArtifactViewer } from "@/components/ArtifactViewer";
import { getTask, type Task, type Artifact } from "@/lib/api";

export default function TaskPage() {
  const params = useParams();
  const taskId = params.id as string;
  const [task, setTask] = useState<Task | null>(null);
  const [activeAgent, setActiveAgent] = useState<string>("orchestrator");
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  useEffect(() => {
    let stopped = false;

    const fetchTask = async () => {
      try {
        const data = await getTask(taskId);
        setTask(data);
        if (data.status === "completed" || data.status === "failed") {
          stopped = true;
        }
      } catch {
        // API not available — use placeholder
        setTask({
          id: taskId,
          goal: "Task in progress...",
          status: "running",
          model: null,
          config: null,
          result: null,
          artifacts: null,
          estimated_cost: 0,
          budget_limit: null,
          user_id: null,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        });
      }
    };

    fetchTask();
    const interval = setInterval(() => {
      if (!stopped) fetchTask();
    }, 5000);
    return () => clearInterval(interval);
  }, [taskId]);

  const handleActiveAgent = useCallback((agent: string) => {
    setActiveAgent(agent);
  }, []);

  const handleNodeClick = useCallback((agentName: string) => {
    setSelectedAgent(agentName === selectedAgent ? null : agentName);
  }, [selectedAgent]);

  const artifacts: Artifact[] = task?.artifacts || [];

  return (
    <div className="h-[calc(100vh-56px)] flex flex-col">
      {/* Task header */}
      <div className="border-b border-border px-6 py-3 flex items-center gap-4">
        <a
          href="/"
          className="flex items-center justify-center w-8 h-8 rounded-lg hover:bg-bg-hover transition-colors"
        >
          <ArrowLeft className="w-4 h-4 text-text-secondary" />
        </a>
        <div className="flex-1 min-w-0">
          <h1 className="text-[14px] font-medium truncate">
            {task?.goal || "Loading..."}
          </h1>
          <div className="flex items-center gap-3 mt-0.5">
            <span className="text-[11px] text-text-tertiary font-mono flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {task?.created_at
                ? new Date(task.created_at).toLocaleTimeString("en-US", { hour12: false })
                : "--:--"}
            </span>
            {task?.estimated_cost ? (
              <span className="text-[11px] text-text-tertiary font-mono flex items-center gap-1">
                <DollarSign className="w-3 h-3" />
                {task.estimated_cost.toFixed(4)}
              </span>
            ) : null}
            {task?.status && (
              <span
                className={`text-[11px] font-medium px-2 py-0.5 rounded-md ${
                  task.status === "running"
                    ? "text-accent-blue bg-accent-blue/10"
                    : task.status === "completed"
                      ? "text-accent-green bg-accent-green/10"
                      : task.status === "failed"
                        ? "text-accent-red bg-accent-red/10"
                        : "text-text-tertiary bg-bg-hover"
                }`}
              >
                {task.status}
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Split view */}
      <div className="flex-1 flex overflow-hidden">
        {/* LEFT: Agent Stream (60%) */}
        <div className="w-[60%] border-r border-border flex flex-col">
          <AgentStream taskId={taskId} onActiveAgent={handleActiveAgent} />

          {/* Artifacts */}
          {artifacts.length > 0 && (
            <div className="border-t border-border p-4 max-h-[200px] overflow-y-auto">
              <ArtifactViewer artifacts={artifacts} />
            </div>
          )}
        </div>

        {/* RIGHT: Workflow Graph (40%) */}
        <div className="w-[40%] flex flex-col">
          <div className="flex items-center justify-between px-5 py-3 border-b border-border">
            <h2 className="text-[13px] font-semibold">Agent Workflow</h2>
            {activeAgent && (
              <span className="text-[11px] text-accent-green font-mono">
                Active: {activeAgent}
              </span>
            )}
          </div>
          <div className="flex-1 relative">
            <WorkflowGraph
              activeAgent={activeAgent}
              onNodeClick={handleNodeClick}
            />
          </div>

          {/* Agent detail panel */}
          {selectedAgent && (
            <div className="border-t border-border p-4">
              <AgentDetail name={selectedAgent} />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function AgentDetail({ name }: { name: string }) {
  const agents: Record<string, { desc: string; model: string }> = {
    orchestrator: { desc: "Plans and coordinates task execution across agents", model: "agentOS/orchestrator" },
    researcher: { desc: "Searches the web and synthesizes information", model: "agentOS/workhorse-gemini" },
    coder: { desc: "Generates, executes, and iterates on code", model: "agentOS/workhorse" },
    browser: { desc: "Navigates websites and extracts data", model: "agentOS/workhorse-kimi" },
    document_writer: { desc: "Creates PDFs, presentations, and documents", model: "agentOS/workhorse-gemini" },
    validator: { desc: "Validates outputs for quality and correctness", model: "agentOS/workhorse" },
  };

  const agent = agents[name] || { desc: "Agent", model: "auto" };

  return (
    <div>
      <h3 className="text-[13px] font-medium capitalize mb-1">{name.replace("_", " ")}</h3>
      <p className="text-[12px] text-text-secondary mb-2">{agent.desc}</p>
      <span className="text-[10px] text-text-tertiary font-mono bg-bg-tertiary px-2 py-0.5 rounded">
        {agent.model}
      </span>
    </div>
  );
}
