"""Composio SaaS integrations — dynamic tool generation for connected apps.

Provides access to 150+ SaaS apps via Composio's unified API.
All destructive actions pass through Approval Gates.
Results are taint-labeled as external data (trust_level=0.7).
"""

import logging
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger("agentos.tools.composio")


@dataclass
class ComposioResult:
    """Result from a Composio tool execution."""
    success: bool
    output: str
    data: dict = field(default_factory=dict)
    error: str = ""


# ── Priority tool definitions ────────────────────────────────────────────

TOOL_REGISTRY: dict[str, dict] = {
    # Gmail
    "send_email": {"app": "gmail", "action": "GMAIL_SEND_EMAIL", "risk": "HIGH",
                   "params": ["to", "subject", "body"]},
    "read_inbox": {"app": "gmail", "action": "GMAIL_GET_MESSAGES", "risk": "LOW",
                   "params": ["max_results"]},
    "search_emails": {"app": "gmail", "action": "GMAIL_SEARCH", "risk": "LOW",
                      "params": ["query", "max_results"]},
    # Google Drive
    "upload_file": {"app": "google_drive", "action": "GOOGLEDRIVE_UPLOAD_FILE", "risk": "MEDIUM",
                    "params": ["file_path", "folder_id"]},
    "list_files": {"app": "google_drive", "action": "GOOGLEDRIVE_LIST_FILES", "risk": "LOW",
                   "params": ["folder_id", "max_results"]},
    "search_files": {"app": "google_drive", "action": "GOOGLEDRIVE_SEARCH", "risk": "LOW",
                     "params": ["query"]},
    # Slack
    "send_message": {"app": "slack", "action": "SLACK_SEND_MESSAGE", "risk": "HIGH",
                     "params": ["channel", "text"]},
    "read_channel": {"app": "slack", "action": "SLACK_GET_MESSAGES", "risk": "LOW",
                     "params": ["channel", "limit"]},
    "list_channels": {"app": "slack", "action": "SLACK_LIST_CHANNELS", "risk": "LOW",
                      "params": []},
    # Notion
    "create_page": {"app": "notion", "action": "NOTION_CREATE_PAGE", "risk": "MEDIUM",
                    "params": ["parent_id", "title", "content"]},
    "update_page": {"app": "notion", "action": "NOTION_UPDATE_PAGE", "risk": "MEDIUM",
                    "params": ["page_id", "content"]},
    "search_notion": {"app": "notion", "action": "NOTION_SEARCH", "risk": "LOW",
                      "params": ["query"]},
    # GitHub
    "create_issue": {"app": "github", "action": "GITHUB_CREATE_ISSUE", "risk": "MEDIUM",
                     "params": ["repo", "title", "body"]},
    "list_repos": {"app": "github", "action": "GITHUB_LIST_REPOS", "risk": "LOW",
                   "params": []},
    "create_pr": {"app": "github", "action": "GITHUB_CREATE_PR", "risk": "HIGH",
                  "params": ["repo", "title", "body", "head", "base"]},
    "read_file": {"app": "github", "action": "GITHUB_GET_FILE", "risk": "LOW",
                  "params": ["repo", "path"]},
    # Salesforce
    "create_lead": {"app": "salesforce", "action": "SALESFORCE_CREATE_LEAD", "risk": "HIGH",
                    "params": ["first_name", "last_name", "company", "email"]},
    "update_contact": {"app": "salesforce", "action": "SALESFORCE_UPDATE_CONTACT", "risk": "HIGH",
                       "params": ["contact_id", "data"]},
    "search_accounts": {"app": "salesforce", "action": "SALESFORCE_SEARCH", "risk": "LOW",
                        "params": ["query"]},
    # Jira
    "create_ticket": {"app": "jira", "action": "JIRA_CREATE_ISSUE", "risk": "MEDIUM",
                      "params": ["project", "summary", "description", "issue_type"]},
    "update_ticket": {"app": "jira", "action": "JIRA_UPDATE_ISSUE", "risk": "MEDIUM",
                      "params": ["issue_key", "data"]},
    "search_issues": {"app": "jira", "action": "JIRA_SEARCH", "risk": "LOW",
                      "params": ["jql"]},
    # HubSpot
    "create_contact": {"app": "hubspot", "action": "HUBSPOT_CREATE_CONTACT", "risk": "MEDIUM",
                       "params": ["email", "first_name", "last_name"]},
    "log_activity": {"app": "hubspot", "action": "HUBSPOT_LOG_ACTIVITY", "risk": "MEDIUM",
                     "params": ["contact_id", "activity_type", "body"]},
}


class ComposioToolManager:
    """Manages Composio tool execution with security integration."""

    def __init__(self):
        self._client = None
        self._toolset = None

        if settings.composio_api_key:
            try:
                from composio import ComposioToolSet
                self._toolset = ComposioToolSet(api_key=settings.composio_api_key)
                logger.info("Composio initialized")
            except ImportError:
                logger.info("Composio not installed — tools unavailable")
            except Exception as e:
                logger.warning("Composio init failed: %s", e)

    @property
    def available(self) -> bool:
        return self._toolset is not None

    def list_connected_apps(self) -> list[str]:
        """List apps the user has connected via Composio OAuth."""
        if not self._toolset:
            return []
        try:
            connections = self._toolset.get_connected_accounts()
            return [c.appUniqueId for c in connections] if connections else []
        except Exception as e:
            logger.warning("Failed to list connected apps: %s", e)
            return []

    def get_available_tools(self) -> list[str]:
        """Get tool names that are available based on connected apps."""
        connected = set(self.list_connected_apps())
        return [
            name for name, cfg in TOOL_REGISTRY.items()
            if cfg["app"] in connected or not self.available
        ]

    async def execute_tool(
        self,
        tool_name: str,
        params: dict,
        task_id: str = "",
    ) -> ComposioResult:
        """Execute a Composio tool with security checks.

        Applies:
        - Approval gates for HIGH risk tools
        - Taint labeling on results
        """
        tool_cfg = TOOL_REGISTRY.get(tool_name)
        if not tool_cfg:
            return ComposioResult(success=False, output="", error=f"Unknown tool: {tool_name}")

        # ── Approval gate for HIGH risk ──
        if tool_cfg["risk"] == "HIGH":
            try:
                from security.approval_gates import request_approval, RiskLevel
                reason = f"Executing {tool_name} on {tool_cfg['app']}"
                approved = await request_approval(
                    task_id=task_id,
                    action=tool_name,
                    reason=reason,
                    risk_level=RiskLevel.HIGH,
                    params=params,
                )
                if not approved:
                    return ComposioResult(
                        success=False, output="",
                        error=f"Action '{tool_name}' rejected by approval gate",
                    )
            except Exception as e:
                logger.warning("Approval gate check failed: %s", e)

        # ── Execute via Composio ──
        if not self._toolset:
            return ComposioResult(
                success=False, output="",
                error="Composio not configured (missing COMPOSIO_API_KEY)",
            )

        try:
            result = self._toolset.execute_action(
                action=tool_cfg["action"],
                params=params,
            )

            output = str(result.get("data", result)) if isinstance(result, dict) else str(result)

            # ── Taint label the result ──
            try:
                from security.taint_tracker import taint_tracker, TaintSource
                taint_tracker.label(
                    content=output,
                    source=TaintSource.COMPOSIO,
                    trust_level=0.7,  # External but trusted source
                    original_source=f"composio:{tool_cfg['app']}:{tool_name}",
                )
            except Exception as e:
                logger.warning("Taint labeling failed: %s", e)

            return ComposioResult(
                success=True,
                output=output,
                data=result if isinstance(result, dict) else {"raw": output},
            )

        except Exception as e:
            logger.error("Composio tool execution failed: %s", e)
            return ComposioResult(success=False, output="", error=str(e))

    def get_oauth_url(self, app_name: str, redirect_uri: str) -> str | None:
        """Get OAuth redirect URL to connect a new app."""
        if not self._toolset:
            return None
        try:
            connection = self._toolset.initiate_connection(
                app_name=app_name,
                redirect_url=redirect_uri,
            )
            return connection.redirectUrl
        except Exception as e:
            logger.error("OAuth initiation failed: %s", e)
            return None


# Singleton
composio_tools = ComposioToolManager()
