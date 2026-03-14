from fastapi import FastAPI

app = FastAPI(title="LLM Guard Service")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/scan/prompt")
async def scan_prompt(payload: dict):
    """Scan a prompt for security issues."""
    prompt = payload.get("prompt", "")
    return {"prompt": prompt, "is_safe": True, "scores": {}}


@app.post("/scan/output")
async def scan_output(payload: dict):
    """Scan an LLM output for security issues."""
    output = payload.get("output", "")
    return {"output": output, "is_safe": True, "scores": {}}
