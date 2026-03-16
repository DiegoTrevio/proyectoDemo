"use client";

import { useCallback, useMemo } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  Brain,
  Search,
  Code2,
  Globe,
  FileText,
  CheckCircle,
} from "lucide-react";

interface WorkflowGraphProps {
  activeAgent?: string;
  onNodeClick?: (agentName: string) => void;
}

const AGENT_NODES = [
  { id: "orchestrator", label: "Orchestrator", icon: Brain, x: 300, y: 0 },
  { id: "researcher", label: "Researcher", icon: Search, x: 100, y: 150 },
  { id: "coder", label: "Coder", icon: Code2, x: 300, y: 150 },
  { id: "browser", label: "Browser", icon: Globe, x: 500, y: 150 },
  { id: "document_writer", label: "Document", icon: FileText, x: 200, y: 300 },
  { id: "validator", label: "Validator", icon: CheckCircle, x: 400, y: 300 },
];

const EDGES_DATA: { source: string; target: string }[] = [
  { source: "orchestrator", target: "researcher" },
  { source: "orchestrator", target: "coder" },
  { source: "orchestrator", target: "browser" },
  { source: "researcher", target: "document_writer" },
  { source: "coder", target: "document_writer" },
  { source: "researcher", target: "validator" },
  { source: "coder", target: "validator" },
  { source: "browser", target: "validator" },
];

function AgentNode({ data }: NodeProps) {
  const Icon = data.icon as typeof Brain;
  const isActive = data.isActive as boolean;

  return (
    <div
      className={`
        px-4 py-3 rounded-xl border transition-all duration-300
        ${
          isActive
            ? "bg-accent-green/10 border-accent-green/40 animate-pulse-glow"
            : "bg-bg-card border-border hover:border-border-hover"
        }
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-border !w-2 !h-2 !border-0" />
      <div className="flex items-center gap-2.5">
        <div
          className={`w-8 h-8 rounded-lg flex items-center justify-center ${
            isActive ? "bg-accent-green/20" : "bg-bg-tertiary"
          }`}
        >
          <Icon
            className={`w-4 h-4 ${isActive ? "text-accent-green" : "text-text-secondary"}`}
          />
        </div>
        <div>
          <div className={`text-[12px] font-medium ${isActive ? "text-accent-green" : "text-text-primary"}`}>
            {data.label as string}
          </div>
          {isActive && (
            <div className="text-[10px] text-accent-green font-mono">Active</div>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-border !w-2 !h-2 !border-0" />
    </div>
  );
}

const nodeTypes = { agent: AgentNode };

export function WorkflowGraph({ activeAgent, onNodeClick }: WorkflowGraphProps) {
  const nodes: Node[] = useMemo(
    () =>
      AGENT_NODES.map((agent) => ({
        id: agent.id,
        type: "agent",
        position: { x: agent.x, y: agent.y },
        data: {
          label: agent.label,
          icon: agent.icon,
          isActive: activeAgent === agent.id,
        },
      })),
    [activeAgent],
  );

  const edges: Edge[] = useMemo(
    () =>
      EDGES_DATA.map((e) => ({
        id: `${e.source}-${e.target}`,
        source: e.source,
        target: e.target,
        style: { stroke: "var(--border)", strokeWidth: 1.5 },
        animated: activeAgent === e.source,
      })),
    [activeAgent],
  );

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick],
  );

  return (
    <div className="w-full h-full">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.5}
        maxZoom={1.5}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
      >
        <Background color="var(--border)" gap={24} size={1} />
        <Controls
          showInteractive={false}
          className="!bg-bg-card !border-border !rounded-lg !shadow-none [&>button]:!bg-bg-card [&>button]:!border-border [&>button]:!text-text-secondary [&>button:hover]:!bg-bg-hover"
        />
      </ReactFlow>
    </div>
  );
}
