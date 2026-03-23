"""Hermes Agent CLI client — spawns Hermes in single-query mode and parses output.

Hermes Agent (by Nous Research) provides:
  - 30+ native tools (terminal, file ops, web, git, browser, vision)
  - 80+ loadable skills
  - Persistent memory across sessions
  - Multi-provider LLM support (Anthropic, OpenAI, OpenRouter, Google)

This client wraps the Hermes CLI (`hermes chat -q <prompt>`) as an async subprocess,
captures stdout/stderr, and parses structured output (session ID, tokens, cost).

Ported from the TypeScript adapter: github.com/NousResearch/hermes-paperclip-adapter
"""

import asyncio
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
    """Result from a Hermes CLI execution."""
    success: bool
    output: str
    session_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    exit_code: int | None = None
    errors: list[str] = field(default_factory=list)
    timed_out: bool = False


class HermesClient:
    """Async client that spawns Hermes CLI as a subprocess.

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
    ):
        self.cli_path = cli_path or settings.hermes_cli_path
        self.model = model or settings.hermes_model
        self.timeout = timeout or settings.hermes_timeout
        self.max_iterations = max_iterations
        self.persist_session = persist_session
        self.enabled_toolsets = enabled_toolsets

    async def is_available(self) -> bool:
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

    async def run(
        self,
        prompt: str,
        session_id: str | None = None,
        extra_env: dict[str, str] | None = None,
        context: str = "",
    ) -> HermesResult:
        """Execute a task via the Hermes CLI.

        Args:
            prompt: The task/query to send to Hermes.
            session_id: Optional session ID to resume a previous session.
            extra_env: Additional environment variables for the subprocess.
            context: Optional context to prepend to the prompt.

        Returns:
            HermesResult with parsed output, tokens, cost, and session info.
        """
        full_prompt = f"{context}\n\n{prompt}" if context else prompt
        args = self._build_args(full_prompt, session_id)
        env = self._build_env(extra_env)

        logger.info(
            "Hermes executing: model=%s timeout=%ds prompt=%s",
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
            )
        except Exception as e:
            return HermesResult(
                success=False,
                output="",
                errors=[f"Failed to spawn Hermes: {e}"],
            )

        stdout = stdout_bytes.decode(errors="replace")
        stderr = stderr_bytes.decode(errors="replace")

        return self._parse_output(stdout, stderr, proc.returncode, timed_out)

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
            "Hermes completed: exit=%s tokens=%d+%d cost=$%.4f session=%s",
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
        )


# ── Singleton client ─────────────────────────────────────────────────────

_client: HermesClient | None = None


def get_hermes_client() -> HermesClient:
    """Get or create the singleton Hermes client."""
    global _client
    if _client is None:
        _client = HermesClient()
    return _client
