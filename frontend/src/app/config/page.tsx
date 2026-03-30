"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Loader2,
  Wrench,
  Bot,
  FolderOpen,
  Server,
  Plus,
  Trash2,
  RefreshCw,
  Play,
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  ChevronDown,
  ChevronUp,
  FileText,
  Shield,
  Copy,
  Check,
} from "lucide-react";
import {
  listSkills,
  deleteSkill,
  createSkill,
  testSkill,
  reloadSkills,
  getSkillTemplate,
  listAgents,
  getAgentsHealth,
  getDeerflowStatus,
  getProjectSections,
  getProjectDrift,
  updateProjectSection,
  type SkillInfo,
  type AgentInfo,
  type ProjectSection,
  type DriftReport,
  type SkillTestResult,
} from "@/lib/api";

type Tab = "skills" | "agents" | "project" | "system";

export default function ConfigPage() {
  const [tab, setTab] = useState<Tab>("skills");

  const tabs: { id: Tab; label: string; icon: typeof Wrench }[] = [
    { id: "skills", label: "Skills", icon: Wrench },
    { id: "agents", label: "Agents", icon: Bot },
    { id: "project", label: "Project", icon: FolderOpen },
    { id: "system", label: "System", icon: Server },
  ];

  return (
    <div className="max-w-[1100px] mx-auto px-6 py-8">
      <h1 className="text-2xl font-semibold mb-1">Configuration</h1>
      <p className="text-[13px] text-text-secondary mb-6">Manage skills, agents, and system settings</p>

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b border-border">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-[13px] font-medium border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? "border-accent-blue text-text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            <t.icon className="w-3.5 h-3.5" />
            {t.label}
          </button>
        ))}
      </div>

      {tab === "skills" && <SkillsTab />}
      {tab === "agents" && <AgentsTab />}
      {tab === "project" && <ProjectTab />}
      {tab === "system" && <SystemTab />}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SKILLS TAB
   ═══════════════════════════════════════════════════════════════════════════ */

function SkillsTab() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [message, setMessage] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const fetch = useCallback(async () => {
    try {
      setSkills(await listSkills());
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  const handleReload = async () => {
    setReloading(true);
    try {
      const r = await reloadSkills();
      setMessage({ type: "ok", text: `Loaded ${r.loaded} skills. Added: ${r.added.length}, Removed: ${r.removed.length}` });
      fetch();
    } catch {
      setMessage({ type: "err", text: "Reload failed" });
    } finally {
      setReloading(false);
    }
  };

  const handleDelete = async (name: string) => {
    try {
      await deleteSkill(name);
      setMessage({ type: "ok", text: `Deleted "${name}"` });
      fetch();
    } catch {
      setMessage({ type: "err", text: `Failed to delete "${name}"` });
    }
  };

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-text-tertiary" /></div>;
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
      {/* Actions bar */}
      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowCreate(!showCreate)}
          className="px-3 py-2 text-[12px] font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors flex items-center gap-1.5"
        >
          <Plus className="w-3 h-3" /> Create Skill
        </button>
        <button
          onClick={handleReload}
          disabled={reloading}
          className="px-3 py-2 text-[12px] font-medium rounded-lg border border-border hover:bg-bg-hover transition-colors flex items-center gap-1.5 disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${reloading ? "animate-spin" : ""}`} /> Reload
        </button>
        <span className="text-[11px] text-text-tertiary ml-auto font-mono">{skills.length} skills</span>
      </div>

      {/* Message */}
      {message && (
        <div className={`px-4 py-2 rounded-lg text-[12px] flex items-center justify-between ${
          message.type === "ok" ? "bg-accent-green/10 text-accent-green border border-accent-green/20" : "bg-accent-red/10 text-accent-red border border-accent-red/20"
        }`}>
          <span>{message.text}</span>
          <button onClick={() => setMessage(null)} className="ml-2 opacity-60 hover:opacity-100">x</button>
        </div>
      )}

      {/* Create form */}
      {showCreate && (
        <SkillCreateForm
          onCreated={() => { fetch(); setShowCreate(false); setMessage({ type: "ok", text: "Skill created" }); }}
          onCancel={() => setShowCreate(false)}
        />
      )}

      {/* Skills grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {skills.map((skill, i) => (
          <motion.div
            key={skill.name}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.03 }}
            className="rounded-xl border border-border bg-bg-card p-4 flex flex-col"
          >
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-[13px] font-semibold">{skill.name}</h3>
              <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                skill.complexity_hint === "simple" ? "bg-accent-green/10 text-accent-green" :
                skill.complexity_hint === "complex" ? "bg-accent-red/10 text-accent-red" :
                "bg-accent-yellow/10 text-accent-yellow"
              }`}>
                {skill.complexity_hint}
              </span>
            </div>
            <p className="text-[11px] text-text-secondary mb-3 line-clamp-2">{skill.description}</p>
            <div className="flex flex-wrap gap-1 mb-3">
              {skill.agents.map((a) => (
                <span key={a} className="text-[10px] px-1.5 py-0.5 rounded bg-bg-hover text-text-secondary border border-border">
                  {a}
                </span>
              ))}
            </div>
            <div className="mt-auto flex items-center justify-between">
              <span className="text-[10px] text-text-tertiary font-mono">{skill.trigger_count} triggers</span>
              <button
                onClick={() => handleDelete(skill.name)}
                className="p-1 rounded hover:bg-accent-red/10 text-text-tertiary hover:text-accent-red transition-colors"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          </motion.div>
        ))}
      </div>
    </motion.div>
  );
}

function SkillCreateForm({ onCreated, onCancel }: { onCreated: () => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [agents, setAgents] = useState("coder");
  const [keywords, setKeywords] = useState("");
  const [taskTypes, setTaskTypes] = useState("code");
  const [instructions, setInstructions] = useState("");
  const [complexity, setComplexity] = useState("medium");
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testGoals, setTestGoals] = useState("");
  const [testResult, setTestResult] = useState<SkillTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [templateCopied, setTemplateCopied] = useState(false);

  const buildData = () => ({
    name: name.trim(),
    description: description.trim(),
    agents: agents.split(",").map((a) => a.trim()).filter(Boolean),
    triggers: {
      keywords: keywords.split("\n").map((k) => k.trim()).filter(Boolean),
      task_types: taskTypes.split(",").map((t) => t.trim()).filter(Boolean),
    },
    instructions: instructions.trim(),
    complexity_hint: complexity,
    tools: [],
    tags: [],
  });

  const handleCreate = async () => {
    setCreating(true);
    setError(null);
    try {
      await createSkill(buildData());
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Creation failed");
    } finally {
      setCreating(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const goals = testGoals.split("\n").map((g) => g.trim()).filter(Boolean);
      if (goals.length === 0) {
        setError("Enter at least one test goal");
        setTesting(false);
        return;
      }
      const result = await testSkill(buildData(), goals);
      setTestResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Test failed");
    } finally {
      setTesting(false);
    }
  };

  const handleCopyTemplate = async () => {
    try {
      const { yaml } = await getSkillTemplate(name || "my-skill");
      await navigator.clipboard.writeText(yaml);
      setTemplateCopied(true);
      setTimeout(() => setTemplateCopied(false), 2000);
    } catch {
      // silent
    }
  };

  return (
    <div className="rounded-xl border border-border bg-bg-card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-[13px] font-semibold">Create New Skill</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCopyTemplate}
            className="text-[11px] text-text-tertiary hover:text-text-secondary flex items-center gap-1"
          >
            {templateCopied ? <Check className="w-3 h-3 text-accent-green" /> : <Copy className="w-3 h-3" />}
            {templateCopied ? "Copied" : "Copy YAML Template"}
          </button>
          <button onClick={onCancel} className="text-[11px] text-text-tertiary hover:text-text-secondary">Cancel</button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1 block">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-skill"
            className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none font-mono"
          />
        </div>
        <div>
          <label className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1 block">Agents (comma-separated)</label>
          <input
            value={agents}
            onChange={(e) => setAgents(e.target.value)}
            placeholder="coder, validator"
            className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none"
          />
        </div>
      </div>

      <div>
        <label className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1 block">Description</label>
        <input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this skill does"
          className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none"
        />
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1 block">Trigger Keywords (one per line, regex)</label>
          <textarea
            value={keywords}
            onChange={(e) => setKeywords(e.target.value)}
            placeholder={"\\bmy-keyword\\b\n\\bother-pattern\\b"}
            rows={3}
            className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none font-mono resize-none"
          />
        </div>
        <div>
          <label className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1 block">Task Types & Complexity</label>
          <input
            value={taskTypes}
            onChange={(e) => setTaskTypes(e.target.value)}
            placeholder="code, research"
            className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none mb-2"
          />
          <select
            value={complexity}
            onChange={(e) => setComplexity(e.target.value)}
            className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none"
          >
            <option value="simple">Simple</option>
            <option value="medium">Medium</option>
            <option value="complex">Complex</option>
          </select>
        </div>
      </div>

      <div>
        <label className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1 block">Instructions (injected into agent context)</label>
        <textarea
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          placeholder="When working on this type of task:\n\n1. First step...\n2. Second step..."
          rows={5}
          className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none font-mono resize-none leading-relaxed"
        />
      </div>

      {/* Test section */}
      <div className="border-t border-border pt-4">
        <label className="text-[10px] text-text-tertiary uppercase tracking-wider mb-1 block">Test Goals (one per line)</label>
        <textarea
          value={testGoals}
          onChange={(e) => setTestGoals(e.target.value)}
          placeholder="Write a REST API for users\nDebug the authentication flow"
          rows={2}
          className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none resize-none mb-2"
        />

        {testResult && (
          <div className="mb-3 space-y-1">
            {testResult.errors.length > 0 && (
              <div className="text-[11px] text-accent-red">
                {testResult.errors.map((e, i) => <p key={i}>[{e.field}] {e.message}</p>)}
              </div>
            )}
            {testResult.matches.map((m, i) => (
              <div key={i} className={`flex items-center gap-2 px-3 py-1.5 rounded text-[11px] ${
                m.matched ? "bg-accent-green/10 text-accent-green" : "bg-bg-hover text-text-tertiary"
              }`}>
                {m.matched ? <CheckCircle2 className="w-3 h-3" /> : <AlertTriangle className="w-3 h-3" />}
                <span className="truncate flex-1">{m.goal}</span>
                <span className="font-mono">{(m.confidence * 100).toFixed(0)}%</span>
              </div>
            ))}
          </div>
        )}

        {error && (
          <p className="text-[11px] text-accent-red mb-2">{error}</p>
        )}

        <div className="flex items-center gap-2">
          <button
            onClick={handleTest}
            disabled={testing}
            className="px-3 py-2 text-[12px] font-medium rounded-lg border border-border hover:bg-bg-hover transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            {testing ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
            Test Skill
          </button>
          <button
            onClick={handleCreate}
            disabled={creating || !name || !instructions}
            className="px-3 py-2 text-[12px] font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            {creating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3" />}
            Create Skill
          </button>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   AGENTS TAB
   ═══════════════════════════════════════════════════════════════════════════ */

function AgentsTab() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [health, setHealth] = useState<Record<string, string>>({});
  const [deerflow, setDeerflow] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      listAgents().catch(() => []),
      getAgentsHealth().catch(() => ({})),
      getDeerflowStatus().catch(() => null),
    ]).then(([a, h, d]) => {
      setAgents(a);
      setHealth(h);
      setDeerflow(d);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-text-tertiary" /></div>;
  }

  const core = agents.filter((a) => a.type === "core");
  const custom = agents.filter((a) => a.type !== "core");

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      {/* DeerFlow status */}
      {deerflow && (
        <div className="rounded-xl border border-border bg-bg-card p-4">
          <div className="flex items-center gap-2 mb-2">
            <Server className="w-3.5 h-3.5 text-accent-blue" />
            <h3 className="text-[13px] font-semibold">DeerFlow 2.0</h3>
            <span className={`text-[10px] px-1.5 py-0.5 rounded ${
              deerflow.status === "available" ? "bg-accent-green/10 text-accent-green" : "bg-accent-red/10 text-accent-red"
            }`}>
              {String(deerflow.status || "unknown")}
            </span>
          </div>
        </div>
      )}

      {/* Core agents */}
      <div>
        <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
          <Shield className="w-3.5 h-3.5 text-accent-blue" />
          Core Agents ({core.length})
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {core.map((agent, i) => (
            <AgentCard key={agent.agent_id} agent={agent} health={health} index={i} />
          ))}
        </div>
      </div>

      {/* Custom agents */}
      {custom.length > 0 && (
        <div>
          <h3 className="text-[13px] font-semibold mb-3 flex items-center gap-2">
            <Wrench className="w-3.5 h-3.5 text-accent-yellow" />
            Custom Agents ({custom.length})
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {custom.map((agent, i) => (
              <AgentCard key={agent.agent_id} agent={agent} health={health} index={i} />
            ))}
          </div>
        </div>
      )}
    </motion.div>
  );
}

function AgentCard({ agent, health, index }: { agent: AgentInfo; health: Record<string, string>; index: number }) {
  const status = health[agent.name];
  const isUp = status === "real" || status === "available";

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.03 }}
      className="rounded-xl border border-border bg-bg-card p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <Bot className={`w-4 h-4 ${agent.type === "core" ? "text-accent-blue" : "text-accent-yellow"}`} />
          <span className="text-[13px] font-semibold capitalize">{agent.name.replace(/_/g, " ")}</span>
        </div>
        <CircleDot className={`w-3.5 h-3.5 ${status ? (isUp ? "text-accent-green" : "text-accent-red") : "text-text-tertiary"}`} />
      </div>
      {agent.model && (
        <p className="text-[11px] text-text-secondary font-mono mb-2">{agent.model.replace("agentOS/", "")}</p>
      )}
      {agent.tools && agent.tools.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {agent.tools.map((tool) => (
            <span key={tool} className="text-[10px] px-1.5 py-0.5 rounded bg-bg-hover text-text-secondary border border-border">
              {tool}
            </span>
          ))}
        </div>
      )}
    </motion.div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   PROJECT TAB
   ═══════════════════════════════════════════════════════════════════════════ */

function ProjectTab() {
  const [sections, setSections] = useState<ProjectSection[]>([]);
  const [drift, setDrift] = useState<DriftReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [saving, setSaving] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const [s, d] = await Promise.all([
        getProjectSections().catch(() => []),
        getProjectDrift().catch(() => null),
      ]);
      setSections(s);
      setDrift(d);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const handleDriftCheck = async () => {
    setChecking(true);
    try {
      setDrift(await getProjectDrift());
    } catch {
      // silent
    } finally {
      setChecking(false);
    }
  };

  const handleExpand = (section: string) => {
    if (expanded === section) {
      setExpanded(null);
    } else {
      setExpanded(section);
      const s = sections.find((sec) => sec.section === section);
      setEditContent(s?.content || "");
    }
  };

  const handleSave = async (section: string) => {
    setSaving(true);
    try {
      await updateProjectSection(section, editContent);
      fetchAll();
      setExpanded(null);
    } catch {
      // silent
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-text-tertiary" /></div>;
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
      {/* Drift score */}
      {drift && (
        <div className="rounded-xl border border-border bg-bg-card p-5 flex items-center gap-4">
          <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-lg font-bold font-mono ${
            drift.healthy ? "bg-accent-green/10 text-accent-green" : "bg-accent-yellow/10 text-accent-yellow"
          }`}>
            {drift.score}
          </div>
          <div className="flex-1">
            <p className="text-[13px] font-semibold">Drift Score</p>
            <p className="text-[11px] text-text-secondary">
              {drift.healthy ? "Project context is up to date" : `${drift.issues.length} issue${drift.issues.length !== 1 ? "s" : ""} found`}
            </p>
          </div>
          <button
            onClick={handleDriftCheck}
            disabled={checking}
            className="px-3 py-2 text-[12px] font-medium rounded-lg border border-border hover:bg-bg-hover transition-colors flex items-center gap-1.5 disabled:opacity-50"
          >
            {checking ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            Check
          </button>
        </div>
      )}

      {/* Drift issues */}
      {drift && drift.issues.length > 0 && (
        <div className="space-y-1">
          {drift.issues.map((issue, i) => (
            <div key={i} className={`px-3 py-2 rounded-lg text-[11px] flex items-center gap-2 ${
              issue.severity === "error" ? "bg-accent-red/10 text-accent-red" : "bg-accent-yellow/10 text-accent-yellow"
            }`}>
              <AlertTriangle className="w-3 h-3 flex-shrink-0" />
              <span>{issue.message}</span>
              {issue.section && <span className="font-mono ml-auto">{issue.section}</span>}
            </div>
          ))}
        </div>
      )}

      {/* Sections */}
      <div className="space-y-2">
        {sections.length === 0 ? (
          <p className="text-[12px] text-text-tertiary text-center py-8">No project context sections configured</p>
        ) : (
          sections.map((sec) => (
            <div key={sec.section} className="rounded-xl border border-border bg-bg-card overflow-hidden">
              <button
                onClick={() => handleExpand(sec.section)}
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-bg-hover transition-colors"
              >
                <div className="flex items-center gap-2">
                  <FileText className="w-3.5 h-3.5 text-text-tertiary" />
                  <span className="text-[13px] font-medium capitalize">{sec.section}</span>
                </div>
                <div className="flex items-center gap-2">
                  {sec.updated_at && (
                    <span className="text-[10px] text-text-tertiary font-mono">
                      {new Date(sec.updated_at).toLocaleDateString()}
                    </span>
                  )}
                  {expanded === sec.section ? <ChevronUp className="w-3 h-3 text-text-tertiary" /> : <ChevronDown className="w-3 h-3 text-text-tertiary" />}
                </div>
              </button>
              {expanded === sec.section && (
                <div className="px-4 pb-4 border-t border-border pt-3">
                  <textarea
                    value={editContent}
                    onChange={(e) => setEditContent(e.target.value)}
                    rows={6}
                    className="w-full px-3 py-2 text-[12px] rounded-lg bg-bg-primary border border-border focus:border-accent-blue focus:outline-none font-mono resize-none leading-relaxed mb-2"
                  />
                  <button
                    onClick={() => handleSave(sec.section)}
                    disabled={saving}
                    className="px-3 py-1.5 text-[12px] font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors disabled:opacity-50 flex items-center gap-1.5"
                  >
                    {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                    Save
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </motion.div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   SYSTEM TAB
   ═══════════════════════════════════════════════════════════════════════════ */

function SystemTab() {
  const [health, setHealth] = useState<Record<string, string>>({});
  const [deerflow, setDeerflow] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      getAgentsHealth().catch(() => ({})),
      getDeerflowStatus().catch(() => null),
    ]).then(([h, d]) => {
      setHealth(h);
      setDeerflow(d);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return <div className="flex justify-center py-12"><Loader2 className="w-5 h-5 animate-spin text-text-tertiary" /></div>;
  }

  const services = [
    { name: "Backend API", status: true, detail: "FastAPI + Uvicorn" },
    { name: "Agent System", status: Object.keys(health).length > 0, detail: `${Object.keys(health).length} agents registered` },
    {
      name: "DeerFlow 2.0",
      status: deerflow?.status === "available",
      detail: deerflow ? String(deerflow.status) : "Not configured",
    },
  ];

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
      {/* Services */}
      <div className="rounded-xl border border-border bg-bg-card overflow-hidden">
        <div className="px-5 py-3 border-b border-border">
          <h3 className="text-[13px] font-semibold">Service Status</h3>
        </div>
        <div className="divide-y divide-border">
          {services.map((svc) => (
            <div key={svc.name} className="flex items-center justify-between px-5 py-3">
              <div className="flex items-center gap-3">
                <span className={`w-2 h-2 rounded-full ${svc.status ? "bg-accent-green" : "bg-accent-red"}`} />
                <span className="text-[13px]">{svc.name}</span>
              </div>
              <span className="text-[11px] text-text-tertiary">{svc.detail}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Agent health detail */}
      <div className="rounded-xl border border-border bg-bg-card overflow-hidden">
        <div className="px-5 py-3 border-b border-border">
          <h3 className="text-[13px] font-semibold">Agent Health</h3>
        </div>
        <div className="divide-y divide-border">
          {Object.entries(health).map(([name, status]) => {
            const isUp = status === "real" || status === "available";
            return (
              <div key={name} className="flex items-center justify-between px-5 py-2.5">
                <div className="flex items-center gap-3">
                  <span className={`w-2 h-2 rounded-full ${isUp ? "bg-accent-green" : "bg-accent-red"}`} />
                  <span className="text-[12px] capitalize">{name.replace(/_/g, " ")}</span>
                </div>
                <span className={`text-[10px] font-mono ${isUp ? "text-accent-green" : "text-accent-red"}`}>
                  {status}
                </span>
              </div>
            );
          })}
          {Object.keys(health).length === 0 && (
            <p className="px-5 py-4 text-[12px] text-text-tertiary">No health data available</p>
          )}
        </div>
      </div>
    </motion.div>
  );
}
