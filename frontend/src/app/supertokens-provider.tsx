"use client";

import { useEffect, useState } from "react";

export function SuperTokensProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    // Initialize SuperTokens on the client side only
    import("@/lib/supertokens")
      .then(({ initSuperTokens }) => {
        initSuperTokens();
        setInitialized(true);
      })
      .catch(() => {
        // SuperTokens not available — continue without it
        setInitialized(true);
      });
  }, []);

  if (!initialized) {
    return null;
  }

  return <>{children}</>;
}
