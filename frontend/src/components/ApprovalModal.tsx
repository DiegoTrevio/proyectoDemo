"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { ShieldAlert, Check, X } from "lucide-react";

interface ApprovalModalProps {
  approvalId: string;
  action: string;
  reason: string;
  riskLevel: string;
  params?: Record<string, string>;
  timeoutSeconds?: number;
  onRespond: (approvalId: string, approved: boolean) => void;
}

export function ApprovalModal({
  approvalId,
  action,
  reason,
  riskLevel,
  params,
  timeoutSeconds = 300,
  onRespond,
}: ApprovalModalProps) {
  const [remaining, setRemaining] = useState(timeoutSeconds);

  useEffect(() => {
    const interval = setInterval(() => {
      setRemaining((r) => {
        if (r <= 1) {
          onRespond(approvalId, false);
          return 0;
        }
        return r - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [approvalId, onRespond]);

  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      >
        <motion.div
          initial={{ scale: 0.95, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.95, opacity: 0 }}
          className="bg-bg-card border border-border rounded-2xl shadow-2xl p-6 max-w-md w-full mx-4"
        >
          {/* Header */}
          <div className="flex items-center gap-3 mb-4">
            <div className="w-10 h-10 rounded-xl bg-accent-red/10 flex items-center justify-center">
              <ShieldAlert className="w-5 h-5 text-accent-red" />
            </div>
            <div>
              <h3 className="font-semibold text-sm">Approval Required</h3>
              <span className="inline-block px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded bg-accent-red/10 text-accent-red">
                {riskLevel}
              </span>
            </div>
          </div>

          {/* Details */}
          <div className="space-y-3 mb-6">
            <div>
              <p className="text-xs text-text-tertiary">Action</p>
              <p className="text-sm font-mono">{action}</p>
            </div>
            <div>
              <p className="text-xs text-text-tertiary">Reason</p>
              <p className="text-sm">{reason}</p>
            </div>
            {params && Object.keys(params).length > 0 && (
              <div>
                <p className="text-xs text-text-tertiary mb-1">Parameters</p>
                <div className="bg-bg-primary rounded-lg p-3 space-y-1">
                  {Object.entries(params).map(([k, v]) => (
                    <div key={k} className="flex gap-2 text-xs">
                      <span className="text-text-tertiary font-mono">{k}:</span>
                      <span className="text-text-secondary break-all">{v}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Timer */}
          <p className="text-xs text-text-tertiary text-center mb-4">
            Auto-reject in {minutes}:{seconds.toString().padStart(2, "0")}
          </p>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={() => onRespond(approvalId, false)}
              className="flex-1 py-2.5 px-4 text-sm font-medium rounded-lg border border-border hover:bg-accent-red/10 hover:border-accent-red/30 hover:text-accent-red transition-colors flex items-center justify-center gap-1.5"
            >
              <X className="w-4 h-4" />
              Reject
            </button>
            <button
              onClick={() => onRespond(approvalId, true)}
              className="flex-1 py-2.5 px-4 text-sm font-medium rounded-lg bg-accent-green text-white hover:bg-accent-green/90 transition-colors flex items-center justify-center gap-1.5"
            >
              <Check className="w-4 h-4" />
              Approve
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
