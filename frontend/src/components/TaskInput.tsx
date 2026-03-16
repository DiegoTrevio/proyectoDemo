"use client";

import { useState, useRef } from "react";
import { Send, ChevronDown } from "lucide-react";
import { CostEstimator } from "./CostEstimator";

const MODELS = [
  { value: "auto", label: "Auto", desc: "Best model for the task" },
  { value: "agentOS/workhorse", label: "Claude Sonnet", desc: "Fast & capable" },
  { value: "agentOS/workhorse-gemini", label: "Gemini Flash", desc: "Documents & research" },
  { value: "agentOS/workhorse-qwen", label: "Qwen", desc: "Cost-effective" },
  { value: "agentOS/workhorse-kimi", label: "Kimi K2.5", desc: "Web browsing" },
];

interface TaskInputProps {
  onSubmit: (goal: string, model: string, budgetLimit: number) => void;
  loading?: boolean;
}

export function TaskInput({ onSubmit, loading }: TaskInputProps) {
  const [goal, setGoal] = useState("");
  const [model, setModel] = useState("auto");
  const [budget, setBudget] = useState(5);
  const [showOptions, setShowOptions] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = () => {
    if (!goal.trim() || loading) return;
    onSubmit(goal.trim(), model, budget);
    setGoal("");
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const selectedModel = MODELS.find((m) => m.value === model) || MODELS[0];

  return (
    <div className="w-full max-w-3xl mx-auto">
      <div className="relative rounded-2xl border border-border bg-bg-card transition-colors focus-within:border-border-hover">
        {/* Textarea */}
        <textarea
          ref={textareaRef}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="What do you want me to do?"
          rows={3}
          className="w-full bg-transparent text-[15px] text-text-primary placeholder:text-text-tertiary px-5 pt-5 pb-3 resize-none focus:outline-none leading-relaxed"
          disabled={loading}
        />

        {/* Bottom bar */}
        <div className="flex items-center justify-between px-4 pb-3">
          <div className="flex items-center gap-2">
            {/* Model selector */}
            <button
              onClick={() => setShowOptions(!showOptions)}
              className="flex items-center gap-1.5 h-8 px-3 rounded-lg bg-bg-tertiary border border-border text-[12px] text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
            >
              {selectedModel.label}
              <ChevronDown className="w-3 h-3" />
            </button>

            {/* Budget display */}
            <span className="text-[11px] text-text-tertiary font-mono">
              Budget: ${budget.toFixed(2)}
            </span>
          </div>

          {/* Submit */}
          <button
            onClick={handleSubmit}
            disabled={!goal.trim() || loading}
            className="flex items-center justify-center w-9 h-9 rounded-xl bg-accent-blue hover:bg-accent-blue-dim disabled:opacity-30 disabled:hover:bg-accent-blue transition-colors"
          >
            <Send className="w-4 h-4 text-white" />
          </button>
        </div>
      </div>

      {/* Options dropdown */}
      {showOptions && (
        <div className="mt-2 rounded-xl border border-border bg-bg-card p-4 animate-slide-up">
          <div className="grid grid-cols-2 gap-4">
            {/* Model picker */}
            <div>
              <label className="text-[11px] font-medium text-text-tertiary uppercase tracking-wider mb-2 block">
                Model
              </label>
              <div className="space-y-1">
                {MODELS.map((m) => (
                  <button
                    key={m.value}
                    onClick={() => setModel(m.value)}
                    className={`w-full text-left px-3 py-2 rounded-lg text-[13px] transition-colors ${
                      model === m.value
                        ? "bg-accent-blue/10 text-accent-blue border border-accent-blue/20"
                        : "hover:bg-bg-hover text-text-secondary"
                    }`}
                  >
                    <span className="font-medium">{m.label}</span>
                    <span className="ml-2 text-[11px] text-text-tertiary">{m.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            {/* Budget slider */}
            <div>
              <label className="text-[11px] font-medium text-text-tertiary uppercase tracking-wider mb-2 block">
                Budget Limit
              </label>
              <div className="space-y-3 pt-1">
                <input
                  type="range"
                  min={0.5}
                  max={50}
                  step={0.5}
                  value={budget}
                  onChange={(e) => setBudget(parseFloat(e.target.value))}
                  className="w-full accent-accent-blue"
                />
                <div className="flex justify-between text-[11px] text-text-tertiary font-mono">
                  <span>$0.50</span>
                  <span className="text-text-primary font-medium">${budget.toFixed(2)}</span>
                  <span>$50.00</span>
                </div>
              </div>

              {/* Cost estimator */}
              {goal.trim() && (
                <div className="mt-4">
                  <CostEstimator goal={goal} model={model} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
