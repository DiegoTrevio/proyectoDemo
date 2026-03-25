/**
 * SuperTokens configuration for AgentOS frontend.
 *
 * Provides email+password authentication via self-hosted SuperTokens.
 * The backend handles session validation — SuperTokens automatically
 * attaches session cookies to all fetch requests.
 */

import SuperTokens from "supertokens-auth-react";
import EmailPasswordReact from "supertokens-auth-react/recipe/emailpassword";
import SessionReact from "supertokens-auth-react/recipe/session";

const API_DOMAIN = process.env.NEXT_PUBLIC_API_URL
  ? new URL(process.env.NEXT_PUBLIC_API_URL).origin
  : "http://localhost:8000";

const WEBSITE_DOMAIN =
  process.env.NEXT_PUBLIC_URL || "http://localhost:3000";

export function initSuperTokens() {
  if (typeof window === "undefined") return;

  // Only init once
  try {
    SuperTokens.init({
      appInfo: {
        appName: "AgentOS",
        apiDomain: API_DOMAIN,
        websiteDomain: WEBSITE_DOMAIN,
        apiBasePath: "/auth",
        websiteBasePath: "/auth",
      },
      recipeList: [
        EmailPasswordReact.init({
          signInAndUpFeature: {
            signUpForm: {
              formFields: [
                { id: "email", label: "Email", placeholder: "you@company.com" },
                { id: "password", label: "Password", placeholder: "********" },
              ],
            },
          },
        }),
        SessionReact.init(),
      ],
    });
  } catch {
    // Already initialized
  }
}
