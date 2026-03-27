"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Bot, Cpu, Wrench, Loader2, CircleDot, Shield } from "lucide-react";
import { listAgents, getAgentsHealth, type AgentInfo } from "@/lib/api";

const TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  core: { bg: "bg-accent-blue/10", text: "text-accent-blue", label: "Core" },
  custom: { bg: "bg-accent-yellow/10", text: "text-accent-yellow", label: "Custom" },
};

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [health, setHealth] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      listAgents().catch(() => []),
      getAgentsHealth().catch(() => ({})),
    ])
      .then(([agentList, healthMap]) => {
        setAgents(agentList);
        setHealth(healthMap);
      })
      .catch(() => setError("Failed to load agents"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 animate-spin text-text-tertiary" />
      </div>
    );
  }

  const coreAgents = agents.filter((a) => a.type === "core");
  const customAgents = agents.filter((a) => a.type !== "core");

  return (
    <div className="max-w-[1200px] mx-auto px-6 py-10">
      <div className="flex items-center justify-between mb-2">
        <h1 className="text-2xl font-semibold">Agents</h1>
        <div className="flex items-center gap-2 text-[11px] text-text-tertiary">
          <span className="flex items-center gap-1">
            <CircleDot className="w-3 h-3 text-accent-green" /> Available
          </span>
          <span className="flex items-center gap-1">
            <CircleDot className="w-3 h-3 text-accent-red" /> Unavailable
          </span>
        </div>
      </div>
      <p className="text-text-secondary text-sm mb-8">
        {coreAgents.length} core agents + {customAgents.length} custom agents
      </p>

      {error && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-accent-red/10 border border-accent-red/20 flex items-center justify-between">
          <span className="text-[13px] text-accent-red">{error}</span>
          <button onClick={() => setError(null)} className="text-accent-red/60 hover:text-accent-red text-sm ml-4">
            Dismiss
          </button>
        </div>
      )}

      {/* Core Agents */}
      <h2 className="text-[13px] font-semibold mb-4 flex items-center gap-2">
        <Shield className="w-4 h-4 text-accent-blue" />
        Core Agents
      </h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-10">
        {coreAgents.map((agent, i) => (
          <AgentCard key={agent.agent_id} agent={agent} health={health} index={i} />
        ))}
      </div>

      {/* Custom Agents */}
      {customAgents.length > 0 && (
        <>
          <h2 className="text-[13px] font-semibold mb-4 flex items-center gap-2">
            <Wrench className="w-4 h-4 text-accent-yellow" />
            Custom Agents
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {customAgents.map((agent, i) => (
              <AgentCard key={agent.agent_id} agent={agent} health={health} index={i} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function AgentCard({
  agent,
  health,
  index,
}: {
  agent: AgentInfo;
  health: Record<string, string>;
  index: number;
}) {
  const typeStyle = TYPE_STYLES[agent.type] || TYPE_STYLES.custom;
  const agentHealth = health[agent.name];
  const isHealthy = agentHealth === "real" || agentHealth === "available";

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="border border-border rounded-xl bg-bg-card p-5 flex flex-col"
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-bg-hover flex items-center justify-center">
            {agent.type === "core" ? (
              <Bot className="w-4 h-4 text-accent-blue" />
            ) : (
              <Cpu className="w-4 h-4 text-accent-yellow" />
            )}
          </div>
          <div>
            <p className="text-[13px] font-semibold capitalize">{agent.name.replace(/_/g, " ")}</p>
            <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${typeStyle.bg} ${typeStyle.text}`}>
              {typeStyle.label}
            </span>
          </div>
        </div>
        <CircleDot
          className={`w-4 h-4 ${agentHealth ? (isHealthy ? "text-accent-green" : "text-accent-red") : "text-text-tertiary"}`}
        />
      </div>

      {/* Model */}
      {agent.model && (
        <div className="mb-3">
          <p className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1">Model</p>
          <p className="text-[12px] text-text-secondary font-mono">{agent.model.replace("agentOS/", "")}</p>
        </div>
      )}

      {/* Tools */}
      {agent.tools && agent.tools.length > 0 && (
        <div>
          <p className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1.5">Tools</p>
          <div className="flex flex-wrap gap-1">
            {agent.tools.map((tool) => (
              <span
                key={tool}
                className="text-[10px] px-2 py-0.5 rounded-md bg-bg-hover text-text-secondary border border-border"
              >
                {tool}
              </span>
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}
