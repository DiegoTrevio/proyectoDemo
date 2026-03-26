"use client";

import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { Check, CreditCard, Loader2, ArrowRight } from "lucide-react";
import { getUsage, createCheckoutSession, type UsageData } from "@/lib/api";

const PLANS = [
  {
    id: "free",
    name: "Free",
    price: 0,
    tasks: 5,
    features: ["5 tasks/month", "Workhorse model only", "Community support"],
  },
  {
    id: "starter",
    name: "Starter",
    price: 29,
    tasks: 100,
    features: ["100 tasks/month", "All models", "10 SaaS integrations", "Email support"],
  },
  {
    id: "pro",
    name: "Pro",
    price: 79,
    tasks: 500,
    popular: true,
    features: ["500 tasks/month", "All models + Opus", "Unlimited integrations", "Priority support", "API access"],
  },
  {
    id: "team",
    name: "Team",
    price: 199,
    tasks: 2000,
    features: ["2,000 tasks/month", "All models + Opus", "RBAC", "Team API keys", "Dedicated support"],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: 999,
    tasks: -1,
    features: ["Unlimited tasks", "On-premise option", "SOC2 compliance", "Custom models", "SLA guarantee"],
  },
];

export default function BillingPage() {
  const [usage, setUsage] = useState<UsageData | null>(null);
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getUsage()
      .then(setUsage)
      .catch(() => setUsage({ plan: "free", tasks_used: 0, tasks_limit: 5, cost_this_month: 0 }))
      .finally(() => setLoading(false));
  }, []);

  const handleUpgrade = async (planId: string) => {
    setUpgrading(planId);
    try {
      const { url } = await createCheckoutSession(planId);
      window.location.href = url;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upgrade failed. Please try again.");
      setUpgrading(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Loader2 className="w-6 h-6 animate-spin text-text-tertiary" />
      </div>
    );
  }

  const currentPlan = usage?.plan || "free";
  const usagePercent = usage && usage.tasks_limit > 0
    ? Math.min(100, (usage.tasks_used / usage.tasks_limit) * 100)
    : 0;

  return (
    <div className="max-w-[1200px] mx-auto px-6 py-10">
      <h1 className="text-2xl font-semibold mb-2">Billing</h1>
      <p className="text-text-secondary text-sm mb-8">Manage your subscription and usage</p>

      {error && (
        <div className="mb-6 px-4 py-3 rounded-lg bg-accent-red/10 border border-accent-red/20 flex items-center justify-between">
          <span className="text-[13px] text-accent-red">{error}</span>
          <button onClick={() => setError(null)} className="text-accent-red/60 hover:text-accent-red text-sm ml-4">
            Dismiss
          </button>
        </div>
      )}

      {/* Current Usage */}
      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="bg-bg-card border border-border rounded-xl p-6 mb-10"
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <p className="text-sm text-text-secondary">Current Plan</p>
            <p className="text-lg font-semibold capitalize">{currentPlan}</p>
          </div>
          <div className="text-right">
            <p className="text-sm text-text-secondary">Cost this month</p>
            <p className="text-lg font-semibold">${usage?.cost_this_month?.toFixed(2) || "0.00"}</p>
          </div>
        </div>

        <div className="mb-2 flex justify-between text-xs text-text-tertiary">
          <span>{usage?.tasks_used || 0} tasks used</span>
          <span>{usage?.tasks_limit === -1 ? "Unlimited" : `${usage?.tasks_limit || 0} limit`}</span>
        </div>
        <div className="h-2 bg-bg-hover rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all ${usagePercent > 80 ? "bg-accent-red" : "bg-accent-blue"}`}
            style={{ width: `${usagePercent}%` }}
          />
        </div>
      </motion.div>

      {/* Plans Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
        {PLANS.map((plan, i) => {
          const isCurrent = plan.id === currentPlan;
          return (
            <motion.div
              key={plan.id}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: i * 0.05 }}
              className={`relative border rounded-xl p-5 flex flex-col ${
                plan.popular
                  ? "border-accent-blue bg-accent-blue/5"
                  : "border-border bg-bg-card"
              }`}
            >
              {plan.popular && (
                <span className="absolute -top-2.5 left-1/2 -translate-x-1/2 px-2.5 py-0.5 bg-accent-blue text-white text-[10px] font-semibold rounded-full uppercase tracking-wider">
                  Popular
                </span>
              )}

              <h3 className="font-semibold text-sm mb-1">{plan.name}</h3>
              <div className="mb-4">
                <span className="text-2xl font-bold">${plan.price}</span>
                <span className="text-text-tertiary text-xs">/month</span>
              </div>

              <ul className="flex-1 space-y-2 mb-5">
                {plan.features.map((f) => (
                  <li key={f} className="flex items-start gap-2 text-xs text-text-secondary">
                    <Check className="w-3.5 h-3.5 mt-0.5 text-accent-green flex-shrink-0" />
                    {f}
                  </li>
                ))}
              </ul>

              {isCurrent ? (
                <button
                  disabled
                  className="w-full py-2 px-3 text-xs font-medium rounded-lg bg-bg-hover text-text-tertiary cursor-default"
                >
                  Current Plan
                </button>
              ) : (
                <button
                  onClick={() => handleUpgrade(plan.id)}
                  disabled={upgrading === plan.id}
                  className="w-full py-2 px-3 text-xs font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors flex items-center justify-center gap-1.5"
                >
                  {upgrading === plan.id ? (
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  ) : (
                    <>
                      Upgrade <ArrowRight className="w-3 h-3" />
                    </>
                  )}
                </button>
              )}
            </motion.div>
          );
        })}
      </div>

      {/* Manage subscription link */}
      <div className="mt-8 text-center">
        <a
          href="/api/v1/billing/portal"
          className="text-sm text-accent-blue hover:underline inline-flex items-center gap-1.5"
        >
          <CreditCard className="w-4 h-4" />
          Manage subscription on Stripe
        </a>
      </div>
    </div>
  );
}
