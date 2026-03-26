"use client";

import { XCircle } from "lucide-react";

export default function BillingCancel() {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
      <XCircle className="w-16 h-16 text-text-tertiary" />
      <h1 className="text-xl font-semibold">Checkout Cancelled</h1>
      <p className="text-text-secondary text-sm">No changes were made to your subscription.</p>
      <a
        href="/billing"
        className="mt-2 px-4 py-2 text-sm font-medium rounded-lg bg-accent-blue text-white hover:bg-accent-blue/90 transition-colors"
      >
        Back to Billing
      </a>
    </div>
  );
}
