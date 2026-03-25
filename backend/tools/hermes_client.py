"""Hermes Agent client — supports both HTTP API (v0.4.0+) and CLI subprocess modes.

Hermes Agent (by Nous Research) provides:
  - 30+ native tools (terminal, file ops, web, git, browser, vision)
  - 80+ loadable skills
  - Persistent memory across sessions
  - Multi-provider LLM support (Anthropic, OpenAI, OpenRouter, Google)
  - OpenAI-compatible API server (/v1/chat/completions) — new in v0.4.0

This client supports two execution modes:
  1. HTTP API (preferred) — calls Hermes's OpenAI-compatible API server
  2. CLI subprocess (fallback) — spawns `hermes chat -q <prompt>`

Ported from the TypeScript adapter: github.com/NousResearch/hermes-paperclip-adapter
"""

import asyncio
import json
import logging
import re
import shutil
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger("agentos.tools.hermes")

# ── Regex patterns (from hermes-paperclip-adapter/src/shared/constants.ts) ──

_SESSION_ID_RE = re.compile(r"session_id:\s*([a-zA-Z0-9_-]+)")
_INPUT_TOKENS_RE = re.compile(r"input[_ ]tokens?:\s*([\d,]+)", re.IGNORECASE)
_OUTPUT_TOKENS_RE = re.compile(r"output[_ ]tokens?:\s*([\d,]+)", re.IGNORECASE)
_COST_RE = re.compile(r"\$\s*([\d.]+)")
_TOOL_OUTPUT_MARKER = "┊"
_THINKING_MARKER = "💭"

# Default configuration
DEFAULT_TIMEOUT = 300  # 5 minutes
GRACE_PERIOD = 10  # seconds to wait after timeout before killing


@dataclass
class HermesResult:
    """Result from a Hermes execution (HTTP or CLI)."""
    success: bool
    output: str
    session_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    exit_code: int | None = None
    errors: list[str] = field(default_factory=list)
    timed_out: bool = False
    mode: str = "cli"  # "http" or "cli"


class HermesClient:
    """Async client for Hermes Agent — HTTP API (v0.4.0+) with CLI fallback.

    Usage:
        client = HermesClient()
        if await client.is_available():
            result = await client.run("Research quantum computing advances in 2026")
            print(result.output)
    """

    def __init__(
        self,
        cli_path: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_iterations: int = 50,
        persist_session: bool = True,
        enabled_toolsets: list[str] | None = None,
        api_url: str | None = None,
    ):
        self.cli_path = cli_path or settings.hermes_cli_path
        self.model = model or settings.hermes_model
        self.timeout = timeout or settings.hermes_timeout
        self.max_iterations = max_iterations
        self.persist_session = persist_session
        self.enabled_toolsets = enabled_toolsets
        self.api_url = api_url or getattr(settings, "hermes_api_url", "")

    @property
    def _use_http(self) -> bool:
        """Whether to use HTTP API mode (preferred over CLI)."""
        return bool(self.api_url)

    async def is_available(self) -> bool:
        """Check if Hermes is accessible (via HTTP API or CLI)."""
        if self._use_http:
            return await self._http_health_check()
        return await self._cli_is_available()

    async def _http_health_check(self) -> bool:
        """Check if Hermes API server is reachable."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.api_url}/health")
                if resp.status_code == 200:
                    logger.debug("Hermes API server healthy at %s", self.api_url)
                    return True
                # Some versions use /v1/models as health indicator
                resp = await client.get(f"{self.api_url}/v1/models")
                return resp.status_code == 200
        except Exception as e:
            logger.debug("Hermes API health check failed: %s", e)
            return False

    async def _cli_is_available(self) -> bool:
        """Check if the Hermes CLI is installed and accessible."""
        path = shutil.which(self.cli_path)
        if not path:
            logger.debug("Hermes CLI not found in PATH: %s", self.cli_path)
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                path, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            version = stdout.decode().strip()
            logger.debug("Hermes CLI version: %s", version)
            return proc.returncode == 0
        except Exception as e:
            logger.debug("Hermes CLI version check failed: %s", e)
            return False

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
        extra_env: dict[str, str] | None = None,
        context: str = "",
        toolsets: list[str] | None = None,
    ) -> HermesResult:
        """Execute a task via Hermes (HTTP API or CLI fallback).

        Args:
            prompt: The task/query to send to Hermes.
            session_id: Optional session ID to resume a previous session.
            extra_env: Additional environment variables (CLI mode only).
            context: Optional context to prepend to the prompt.
            toolsets: Optional toolsets to enable for this execution.

        Returns:
            HermesResult with parsed output, tokens, cost, and session info.
        """
        if self._use_http:
            return await self._run_http(prompt, session_id, context, toolsets)
        return await self._run_cli(prompt, session_id, extra_env, context)

    # ── HTTP API mode (v0.4.0+) ────────────────────────────────────────────

    async def _run_http(
        self,
        prompt: str,
        session_id: str | None = None,
        context: str = "",
        toolsets: list[str] | None = None,
    ) -> HermesResult:
        """Execute via Hermes's OpenAI-compatible API server."""
        import httpx

        full_prompt = f"{context}\n\n{prompt}" if context else prompt

        messages = []
        if context:
            messages.append({"role": "system", "content": context})
        messages.append({"role": "user", "content": prompt if context else full_prompt})

        payload: dict = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 8192,
        }

        # Pass toolsets and session via extra_body (Hermes extension)
        extra: dict = {}
        if toolsets:
            extra["toolsets"] = toolsets
        if session_id and self.persist_session:
            extra["session_id"] = session_id
        if self.max_iterations:
            extra["max_iterations"] = self.max_iterations
        if extra:
            payload["extra_body"] = extra

        logger.info(
            "Hermes HTTP executing: model=%s url=%s prompt=%s",
            self.model, self.api_url, prompt[:80],
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.api_url}/v1/chat/completions",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )

                if resp.status_code != 200:
                    error_text = resp.text
                    logger.warning("Hermes API error %d: %s", resp.status_code, error_text[:200])
                    return HermesResult(
                        success=False,
                        output="",
                        errors=[f"Hermes API returned {resp.status_code}: {error_text[:500]}"],
                        mode="http",
                    )

                data = resp.json()
                return self._parse_http_response(data)

        except httpx.TimeoutException:
            logger.warning("Hermes HTTP timed out after %ds", self.timeout)
            return HermesResult(
                success=False,
                output="",
                errors=[f"Hermes API timed out after {self.timeout}s"],
                timed_out=True,
                mode="http",
            )
        except Exception as e:
            logger.warning("Hermes HTTP request failed: %s", e)
            return HermesResult(
                success=False,
                output="",
                errors=[f"Hermes API request failed: {e}"],
                mode="http",
            )

    def _parse_http_response(self, data: dict) -> HermesResult:
        """Parse OpenAI-compatible response from Hermes API."""
        choices = data.get("choices", [])
        output = ""
        if choices:
            message = choices[0].get("message", {})
            output = message.get("content", "")

        usage = data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # Hermes may include cost in usage extension
        cost = usage.get("cost", 0.0)

        # Session ID from Hermes extension
        session_id = data.get("session_id") or data.get("id")

        logger.info(
            "Hermes HTTP completed: tokens=%d+%d cost=$%.4f session=%s",
            input_tokens, output_tokens, cost, session_id or "none",
        )

        return HermesResult(
            success=True,
            output=output,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            exit_code=0,
            mode="http",
        )

    # ── CLI subprocess mode (legacy) ───────────────────────────────────────

    async def _run_cli(
        self,
        prompt: str,
        session_id: str | None = None,
        extra_env: dict[str, str] | None = None,
        context: str = "",
    ) -> HermesResult:
        """Execute a task via the Hermes CLI subprocess."""
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        args = self._build_args(full_prompt, session_id)
        env = self._build_env(extra_env)

        logger.info(
            "Hermes CLI executing: model=%s timeout=%ds prompt=%s",
            self.model, self.timeout, prompt[:80],
        )

        timed_out = False
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.timeout,
                )
            except asyncio.TimeoutError:
                timed_out = True
                logger.warning("Hermes timed out after %ds, sending SIGTERM", self.timeout)
                proc.terminate()
                try:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        proc.communicate(), timeout=GRACE_PERIOD,
                    )
                except asyncio.TimeoutError:
                    logger.warning("Hermes did not exit after grace period, killing")
                    proc.kill()
                    stdout_bytes, stderr_bytes = await proc.communicate()

        except FileNotFoundError:
            return HermesResult(
                success=False,
                output="",
                errors=[f"Hermes CLI not found: {self.cli_path}"],
                mode="cli",
            )
        except Exception as e:
            return HermesResult(
                success=False,
                output="",
                errors=[f"Failed to spawn Hermes: {e}"],
                mode="cli",
            )

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        return self._parse_output(stdout, stderr, proc.returncode, timed_out)

    def _build_args(self, prompt: str, session_id: str | None = None) -> list[str]:
        """Build CLI arguments for a Hermes invocation."""
        args = [
            self.cli_path,
            "chat",
            "-q", prompt,     # Single-query mode
            "-Q",             # Quiet mode (no interactive UI)
            "-m", self.model,
        ]

        if self.max_iterations:
            args.extend(["--max-iterations", str(self.max_iterations)])

        if session_id and self.persist_session:
            args.extend(["--resume", session_id])

        if self.enabled_toolsets:
            for toolset in self.enabled_toolsets:
                args.extend(["--tools", toolset])

        return args

    def _build_env(self, extra_env: dict[str, str] | None = None) -> dict[str, str]:
        """Build environment variables for the Hermes subprocess."""
        import os
        env = dict(os.environ)

        # Forward LLM API keys from AgentOS settings
        key_map = {
            "ANTHROPIC_API_KEY": settings.anthropic_api_key,
            "OPENAI_API_KEY": settings.openai_api_key,
            "GOOGLE_API_KEY": settings.google_api_key,
        }
        for key, value in key_map.items():
            if value:
                env[key] = value

        if extra_env:
            env.update(extra_env)

        return env

    def _parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        timed_out: bool,
    ) -> HermesResult:
        """Parse Hermes CLI stdout/stderr into a structured result."""
        # Extract session ID
        session_match = _SESSION_ID_RE.search(stdout) or _SESSION_ID_RE.search(stderr)
        session_id = session_match.group(1) if session_match else None

        # Extract token counts
        input_tokens = 0
        output_tokens = 0
        input_match = _INPUT_TOKENS_RE.search(stdout) or _INPUT_TOKENS_RE.search(stderr)
        output_match = _OUTPUT_TOKENS_RE.search(stdout) or _OUTPUT_TOKENS_RE.search(stderr)
        if input_match:
            input_tokens = int(input_match.group(1).replace(",", ""))
        if output_match:
            output_tokens = int(output_match.group(1).replace(",", ""))

        # Extract cost
        cost = 0.0
        cost_match = _COST_RE.search(stderr) or _COST_RE.search(stdout)
        if cost_match:
            try:
                cost = float(cost_match.group(1))
            except ValueError:
                pass

        # Filter stderr for real errors (exclude INFO/DEBUG/warn noise)
        errors = []
        if stderr:
            for line in stderr.splitlines():
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                # Skip log-level noise
                if any(skip in line_stripped for skip in ("INFO", "DEBUG", "warn", "Warning:")):
                    continue
                if any(kw in line_stripped.lower() for kw in ("error", "exception", "traceback")):
                    errors.append(line_stripped)
            errors = errors[:5]  # Cap at 5 error lines

        # Clean output: remove tool markers and thinking blocks
        clean_lines = []
        for line in stdout.splitlines():
            if line.startswith(_TOOL_OUTPUT_MARKER):
                continue
            if _THINKING_MARKER in line:
                continue
            clean_lines.append(line)
        output = "\n".join(clean_lines).strip()

        success = exit_code == 0 and not timed_out
        if timed_out:
            errors.append(f"Process timed out after {self.timeout}s")

        logger.info(
            "Hermes CLI completed: exit=%s tokens=%d+%d cost=$%.4f session=%s",
            exit_code, input_tokens, output_tokens, cost, session_id or "none",
        )

        return HermesResult(
            success=success,
            output=output,
            session_id=session_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            exit_code=exit_code,
            errors=errors,
            timed_out=timed_out,
            mode="cli",
        )


# ── Singleton client ─────────────────────────────────────────────────────

_client: HermesClient | None = None


def get_hermes_client() -> HermesClient:
    """Get or create the singleton Hermes client."""
    global _client
    if _client is None:
        _client = HermesClient()
    return _client
