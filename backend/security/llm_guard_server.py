"""LLM Guard REST API service — runs on port 8080 in Docker.

Provides /scan/prompt and /scan/output endpoints for the security middleware.
Uses the scanners configured in llm_guard_config.py.
"""

from fastapi import FastAPI
from pydantic import BaseModel

from security.llm_guard_config import scan_input, scan_output

app = FastAPI(title="LLM Guard Service")


class PromptScanRequest(BaseModel):
    prompt: str
    client_id: str = "default"


class OutputScanRequest(BaseModel):
    output: str
    prompt: str = ""


class ScanResponse(BaseModel):
    text: str
    is_safe: bool
    risks: dict[str, float]
    details: list[str]


@app.get("/health")
async def health():
    return {"status": "ok", "service": "llm-guard"}


@app.post("/scan/prompt", response_model=ScanResponse)
async def scan_prompt_endpoint(payload: PromptScanRequest):
    """Scan a prompt for security issues (PII, injection, toxicity)."""
    result = scan_input(payload.prompt)
    return ScanResponse(
        text=result.sanitized_text,
        is_safe=result.is_safe,
        risks=result.risks,
        details=result.details,
    )


@app.post("/scan/output", response_model=ScanResponse)
async def scan_output_endpoint(payload: OutputScanRequest):
    """Scan an LLM output for security issues (PII leakage, sensitive data)."""
    result = scan_output(payload.output, payload.prompt)
    return ScanResponse(
        text=result.sanitized_text,
        is_safe=result.is_safe,
        risks=result.risks,
        details=result.details,
    )
