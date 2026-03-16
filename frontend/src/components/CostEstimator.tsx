"use client";

import { useState, useEffect, useRef } from "react";
import { estimateCost, type CostEstimate } from "@/lib/api";

interface CostEstimatorProps {
  goal: string;
  model: string;
}

export function CostEstimator({ goal, model }: CostEstimatorProps) {
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => {
    if (!goal.trim()) {
      setEstimate(null);
      return;
    }

    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const est = await estimateCost(goal, model !== "auto" ? model : undefined);
        setEstimate(est);
      } catch {
        // API not available — show placeholder
        setEstimate({
          model: model === "auto" ? "agentOS/workhorse" : model,
          estimated_tokens: Math.max(500, goal.length * 10),
          estimated_cost: Math.max(0.01, goal.length * 0.0005),
          breakdown: {
            input_cost: goal.length * 0.0002,
            output_cost: goal.length * 0.0003,
          },
        });
      } finally {
        setLoading(false);
      }
    }, 600);

    return () => clearTimeout(debounceRef.current);
  }, [goal, model]);

  if (!estimate && !loading) return null;

  return (
    <div className="rounded-lg border border-border bg-bg-secondary p-3">
      <div className="text-[11px] font-medium text-text-tertiary uppercase tracking-wider mb-2">
        Estimated Cost
      </div>
      {loading ? (
        <div className="h-4 w-24 rounded bg-bg-hover animate-pulse" />
      ) : estimate ? (
        <div className="space-y-1.5">
          <div className="flex items-baseline gap-2">
            <span className="text-lg font-semibold text-text-primary font-mono">
              ${estimate.estimated_cost.toFixed(4)}
            </span>
            <span className="text-[11px] text-text-tertiary">estimated</span>
          </div>
          <div className="flex gap-4 text-[11px] text-text-tertiary font-mono">
            <span>~{estimate.estimated_tokens.toLocaleString()} tokens</span>
            <span>{estimate.model.replace("agentOS/", "")}</span>
          </div>
          <div className="flex gap-4 text-[10px] text-text-tertiary font-mono">
            <span>Input: ${estimate.breakdown.input_cost.toFixed(4)}</span>
            <span>Output: ${estimate.breakdown.output_cost.toFixed(4)}</span>
          </div>
        </div>
      ) : null}
    </div>
  );
}
