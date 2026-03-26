"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2 } from "lucide-react";

export default function BillingSuccess() {
  const router = useRouter();

  useEffect(() => {
    const timer = setTimeout(() => router.push("/"), 3000);
    return () => clearTimeout(timer);
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
      <CheckCircle2 className="w-16 h-16 text-accent-green" />
      <h1 className="text-xl font-semibold">Subscription Activated</h1>
      <p className="text-text-secondary text-sm">Redirecting to dashboard...</p>
    </div>
  );
}
