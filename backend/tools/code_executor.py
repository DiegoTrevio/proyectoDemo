"""E2B sandbox code executor for AgentOS.

Executes code in ephemeral, secure E2B sandboxes.
Each execution creates a sandbox, runs code, captures output, and destroys the sandbox.
"""

import logging
from dataclasses import dataclass, field

from config.settings import settings

logger = logging.getLogger("agentos.tools.code_executor")

_EXECUTION_TIMEOUT = 60  # seconds per execution


@dataclass
class ExecutionResult:
    """Result of a code execution in E2B sandbox."""
    stdout: str = ""
    stderr: str = ""
    files: list[dict] = field(default_factory=list)  # [{name, content_b64}]
    exit_code: int = -1
    error: str | None = None
    timed_out: bool = False

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.error and not self.timed_out

    def to_dict(self) -> dict:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "files": self.files,
            "exit_code": self.exit_code,
            "error": self.error,
            "timed_out": self.timed_out,
        }


class CodeExecutor:
    """Executes code in E2B ephemeral sandboxes."""

    def __init__(self):
        self.api_key = settings.e2b_api_key

    async def execute(
        self,
        code: str,
        language: str = "python",
        dependencies: list[str] | None = None,
        timeout: int = _EXECUTION_TIMEOUT,
    ) -> ExecutionResult:
        """Execute code in an E2B sandbox.

        Args:
            code: Source code to execute.
            language: Programming language (currently only 'python' supported).
            dependencies: pip packages to install before execution.
            timeout: Max seconds for execution.

        Returns:
            ExecutionResult with stdout, stderr, files, and exit code.
        """
        if not self.api_key:
            logger.warning("E2B API key not configured — code will NOT be executed")
            return ExecutionResult(
                stdout="",
                stderr="E2B_API_KEY not configured. Code was NOT executed. Set E2B_API_KEY in .env to enable sandbox execution.",
                exit_code=1,
            )

        sandbox = None
        try:
            from e2b_code_interpreter import Sandbox

            sandbox = Sandbox(api_key=self.api_key, timeout=timeout)

            # Install dependencies if specified
            if dependencies:
                deps_str = " ".join(dependencies)
                logger.info("Installing dependencies: %s", deps_str)
                install_result = sandbox.run_code(f"import subprocess; subprocess.check_call(['pip', 'install', '-q', {', '.join(repr(d) for d in dependencies)}])")
                if install_result.error:
                    logger.warning("Dependency install warning: %s", install_result.error.value[:200])

            # Execute the code
            logger.info("Executing code in E2B sandbox (%d chars)", len(code))
            result = sandbox.run_code(code)

            # Collect output
            stdout_parts = []
            stderr_parts = []
            for log in result.logs.stdout:
                stdout_parts.append(log)
            for log in result.logs.stderr:
                stderr_parts.append(log)

            stdout = "\n".join(stdout_parts)
            stderr = "\n".join(stderr_parts)

            # Collect generated files (charts, images, etc.)
            files = []
            if result.results:
                for r in result.results:
                    if hasattr(r, "png") and r.png:
                        files.append({"name": "output.png", "content_b64": r.png})
                    if hasattr(r, "svg") and r.svg:
                        files.append({"name": "output.svg", "content_b64": r.svg})
                    if hasattr(r, "text") and r.text:
                        stdout += f"\n{r.text}"

            exit_code = 1 if result.error else 0
            error = result.error.value if result.error else None

            return ExecutionResult(
                stdout=stdout.strip(),
                stderr=stderr.strip(),
                files=files,
                exit_code=exit_code,
                error=error,
            )

        except TimeoutError:
            logger.error("E2B execution timed out after %ds", timeout)
            return ExecutionResult(
                stderr=f"Execution timed out after {timeout} seconds",
                exit_code=124,
                timed_out=True,
            )
        except Exception as e:
            logger.exception("E2B execution failed")
            return ExecutionResult(
                stderr=str(e),
                exit_code=1,
                error=f"Sandbox error: {e}",
            )
        finally:
            if sandbox:
                try:
                    sandbox.kill()
                    logger.info("E2B sandbox destroyed")
                except Exception as e:
                    logger.warning("Failed to destroy sandbox: %s", e)

    def _detect_dependencies(self, code: str) -> list[str]:
        """Auto-detect pip dependencies from import statements."""
        import re

        # Map of import name → pip package name
        _IMPORT_MAP = {
            "matplotlib": "matplotlib",
            "numpy": "numpy",
            "pandas": "pandas",
            "requests": "requests",
            "scipy": "scipy",
            "sklearn": "scikit-learn",
            "PIL": "Pillow",
            "cv2": "opencv-python",
            "plotly": "plotly",
            "seaborn": "seaborn",
            "flask": "flask",
            "fastapi": "fastapi",
            "bs4": "beautifulsoup4",
            "yaml": "pyyaml",
        }

        imports = set()
        for match in re.finditer(r"^\s*(?:import|from)\s+(\w+)", code, re.MULTILINE):
            module = match.group(1)
            if module in _IMPORT_MAP:
                imports.add(_IMPORT_MAP[module])

        return sorted(imports)
