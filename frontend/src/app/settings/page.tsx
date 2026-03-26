"use client";

import { useState, useEffect, useCallback } from "react";
import { motion } from "framer-motion";
import {
  Key,
  Plus,
  Trash2,
  Loader2,
  Copy,
  Check,
  CreditCard,
  User,
} from "lucide-react";
import {
  listApiKeys,
  createApiKey,
  revokeApiKey,
  hasSession,
  type ApiKeyInfo,
} from "@/lib/api";

type Tab = "profile" | "apikeys" | "billing";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("profile");

  return (
    <div className="max-w-[900px] mx-auto px-6 py-10">
      <h1 className="text-2xl font-semibold mb-6">Settings</h1>

      {/* Tabs */}
      <div className="flex gap-1 mb-8 border-b border-border">
        {([
          { id: "profile" as Tab, label: "Profile", icon: User },
          { id: "apikeys" as Tab, label: "API Keys", icon: Key },
          { id: "billing" as Tab, label: "Billing", icon: CreditCard },
        ]).map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.id
                ? "border-accent-blue text-text-primary"
                : "border-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            <t.icon className="w-4 h-4" />
            {t.label}
          </button>
        ))}
      </div>

      {tab === "profile" && <ProfileTab />}
      {tab === "apikeys" && <ApiKeysTab />}
      {tab === "billing" && <BillingTab />}
    </div>
  );
}

function ProfileTab() {
  const [sessionActive, setSessionActive] = useState(false);

  useEffect(() => {
    hasSession().then(setSessionActive);
  }, []);

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      <div className="bg-bg-card border border-border rounded-xl p-6">
        <h3 className="font-medium mb-4">Account</h3>
        <div className="space-y-3 text-sm">
          <div className="flex justify-between">
            <span className="text-text-secondary">Authentication</span>
            <span className={sessionActive ? "text-accent-green" : "text-text-tertiary"}>
              {sessionActive ? "SuperTokens Session Active" : "API Key Only"}
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-text-secondary">Session Status</span>
            <span className="flex items-center gap-1.5">
              <span className={`w-2 h-2 rounded-full ${sessionActive ? "bg-accent-green" : "bg-text-tertiary"}`} />
              {sessionActive ? "Active" : "No session"}
            </span>
          </div>
        </div>
      </div>
    </motion.div>
  );
}

function ApiKeysTab() {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyValue, setNewKeyValue] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const fetchKeys = useCallback(async () => {
    try {
      const data = await listApiKeys();
      setKeys(data);
    } catch {
      // Keys endpoint may not be available
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchKeys(); }, [fetchKeys]);

  const handleCreate = async () => {
    if (!newKeyName.trim()) return;
    setCreating(true);
    try {
      const { key } = await createApiKey(newKeyName.trim());
      setNewKeyValue(key);
      setNewKeyName("");
      fetchKeys();
    } catch {
      // Handle error
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (keyId: string) => {
    try {
      await revokeApiKey(keyId);
      fetchKeys();
    } catch {
      // Handle error
    }
  };

  const handleCopy = () => {
    if (newKeyValue) {
      navigator.clipboard.writeText(newKeyValue);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  if (loading) {
    return <Loader2 className="w-5 h-5 animate-spin text-text-tertiary" />;
  }

  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-6">
      {/* New key result */}
      {newKeyValue && (
        <div className="bg-accent-green/10 border border-accent-green/30 rounded-xl p-4">
          <p className="text-sm font-medium mb-2">New API Key Created</p>
          <p className="text-xs text-text-secondary mb-2">Copy it now — it won&apos;t be shown again.</p>
          <div className="flex items-center gap-2">
            <code className="flex-1 bg-bg-primary px-3 py-2 rounded-lg text-xs font-mono break-all">
              {newKeyValue}
            </code>
            <button onClick={handleCopy} className="p-2 rounded-lg hover:bg-bg-hover transition-colors">
              {copied ? <Check className="w-4 h-4 text-accent-green" /> : <Copy className="w-4 h-4" />}
            </button>
          </div>
        </div>
      )}

      {/* Create new key */}
      <div className="bg-bg-card border border-border rounded-xl p-6">
        <h3 className="font-medium mb-4">Create API Key</h3>
        <div className="flex gap-2">
          <input
            type="text"
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="Key name (e.g. Production)"
            className="flex-1 bg-bg-primary border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-accent-blue"
            onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          />
          <button
            onClick={handleCreate}
            disabled={creating || !newKeyName.trim()}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors disabled:opacity-50 flex items-center gap-1.5"
          >
            {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
            Create
          </button>
        </div>
      </div>

      {/* Key list */}
      <div className="bg-bg-card border border-border rounded-xl overflow-hidden">
        <div className="px-6 py-4 border-b border-border">
          <h3 className="font-medium">Active Keys</h3>
        </div>
        {keys.length === 0 ? (
          <p className="px-6 py-8 text-sm text-text-tertiary text-center">No API keys yet</p>
        ) : (
          <div className="divide-y divide-border">
            {keys.map((key) => (
              <div key={key.id} className="flex items-center justify-between px-6 py-3">
                <div>
                  <p className="text-sm font-medium">{key.name}</p>
                  <p className="text-xs text-text-tertiary font-mono">{key.key_prefix}...</p>
                </div>
                <div className="flex items-center gap-4">
                  <span className="text-xs text-text-tertiary">
                    {key.last_used_at ? `Used ${new Date(key.last_used_at).toLocaleDateString()}` : "Never used"}
                  </span>
                  <button
                    onClick={() => handleRevoke(key.id)}
                    className="p-1.5 rounded-md hover:bg-accent-red/10 text-text-tertiary hover:text-accent-red transition-colors"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </motion.div>
  );
}

function BillingTab() {
  return (
    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="space-y-4">
      <div className="bg-bg-card border border-border rounded-xl p-6">
        <h3 className="font-medium mb-4">Subscription</h3>
        <p className="text-sm text-text-secondary mb-4">
          Manage your plan, payment methods, and invoices.
        </p>
        <div className="flex gap-3">
          <a
            href="/billing"
            className="px-4 py-2 text-sm font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors"
          >
            View Plans
          </a>
          <a
            href="/api/v1/billing/portal"
            className="px-4 py-2 text-sm font-medium rounded-lg border border-border hover:bg-bg-hover transition-colors"
          >
            Stripe Portal
          </a>
        </div>
      </div>
    </motion.div>
  );
}
