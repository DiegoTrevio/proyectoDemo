"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export default function AuthPage() {
  const router = useRouter();
  const [AuthUI, setAuthUI] = useState<React.ComponentType | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadAuth() {
      try {
        const { initSuperTokens } = await import("@/lib/supertokens");
        initSuperTokens();

        const { SignInAndUp } = await import(
          "supertokens-auth-react/recipe/emailpassword/prebuiltui"
        );
        setAuthUI(() => SignInAndUp);
      } catch {
        setError(
          "Authentication service unavailable. Check that SuperTokens is running."
        );
      }
    }
    loadAuth();
  }, []);

  // Check if already authenticated
  useEffect(() => {
    async function checkSession() {
      try {
        const Session = await import("supertokens-auth-react/recipe/session");
        if (await Session.doesSessionExist()) {
          router.push("/");
        }
      } catch {
        // Not authenticated — stay on auth page
      }
    }
    checkSession();
  }, [router]);

  if (error) {
    return (
      <div className="max-w-md mx-auto px-6 py-24">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold tracking-tight mb-2">AgentOS</h1>
          <p className="text-[13px] text-text-secondary">Authentication</p>
        </div>
        <div className="px-4 py-3 rounded-lg bg-accent-red/10 border border-accent-red/20 text-[13px] text-accent-red">
          {error}
        </div>
        <p className="mt-4 text-[12px] text-text-tertiary text-center">
          You can also use an API key directly from the{" "}
          <a href="/" className="text-accent-blue hover:underline">
            dashboard
          </a>
          .
        </p>
      </div>
    );
  }

  if (!AuthUI) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="text-text-tertiary text-[13px]">Loading...</div>
      </div>
    );
  }

  return (
    <div className="max-w-md mx-auto px-6 py-12">
      <div className="text-center mb-8">
        <h1 className="text-2xl font-bold tracking-tight mb-2">
          Welcome to AgentOS
        </h1>
        <p className="text-[13px] text-text-secondary">
          Sign in or create an account to get started.
        </p>
      </div>
      <AuthUI />
    </div>
  );
}
