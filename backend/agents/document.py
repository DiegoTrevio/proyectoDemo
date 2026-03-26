"""Document Agent — generates PDFs, PPTX, DOCX, and Excel files.

Model routing:
  - Simple templates → Qwen (agentOS/workhorse-qwen)
  - Standard documents → Gemini 3 Flash (agentOS/workhorse-gemini)
  - Complex reports → Gemini with extended context

Integrates Nano Banana 2 (Gemini image generation) for presentation images.
"""

import base64
import json
import logging

from agents.base_agent import AbstractAgent, AgentResult
from agents.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from config.model_router import select_model
from tools.file_generator import generate_docx, generate_excel, generate_pdf, generate_pptx
from tools.image_generator import generate_image, generate_presentation_images

logger = logging.getLogger("agentos.agents.document")

_SYSTEM_PROMPT = """You are a professional document creator. You generate well-structured, polished documents.

Rules:
1. Content must be clear, professional, and well-organized
2. Use proper headings, bullet points, and formatting
3. For presentations, keep bullet points concise (max 6 per slide)
4. For reports, include executive summary, sections, and conclusions
5. Respond ONLY with valid JSON"""

_PLAN_PROMPT = """Create a document based on this task. Determine the best format and generate the content.

Task: {goal}

Context: {context}

Respond with JSON only:
{{
  "format": "pptx"|"pdf"|"docx"|"xlsx",
  "title": "Document Title",
  "slides": [  // for pptx
    {{"title": "Slide Title", "content": "Bullet points or text", "image_prompt": "optional image description"}}
  ],
  "sections": [  // for pdf/docx
    {{"heading": "Section Title", "content": "Section content..."}}
  ],
  "data": [  // for xlsx
    {{"col1": "val1", "col2": "val2"}}
  ]
}}"""


class DocumentAgent(AbstractAgent):
    """Generates professional documents: PDF, PPTX, DOCX, Excel."""

    name = "document_writer"
    task_type = "document"
    default_complexity = "medium"

    def __init__(self, circuit_breaker: CircuitBreaker | None = None):
        cb_config = CircuitBreakerConfig(
            max_iterations=6,
            timeout_seconds=300,
        )
        super().__init__(circuit_breaker or CircuitBreaker(cb_config))

    def _select_model(self, goal: str) -> str:
        """Select model via cost-first router with automatic fallback."""
        goal_lower = goal.lower()
        simple_signals = ["template", "simple", "basic", "quick", "list", "table"]
        complexity = "simple" if any(s in goal_lower for s in simple_signals) else "medium"
        return select_model("document", complexity).model

    async def execute(self, task: dict, context: dict) -> AgentResult:
        """Generate a document based on the task description."""
        goal = task.get("goal", "")
        task_id = task.get("task_id", "unknown")
        cb_state = self.cb.new_state()

        model = self._select_model(goal)
        logger.info("Document agent: model=%s goal=%s", model, goal[:80])

        # Build context from prior results
        ctx_text = ""
        for r in context.get("prior_results", [])[-3:]:
            ctx_text += r.get("output", "")[:1000] + "\n"

        # ── Step 1: Generate document plan + content via LLM ──
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _PLAN_PROMPT.format(
                goal=goal, context=ctx_text or "None",
            )},
        ]

        try:
            response_text, cb_state = await self.call_llm(
                messages, cb_state, model_override=model, max_tokens=8192,
            )
            plan = self._parse_json(response_text)
        except Exception as e:
            logger.exception("Document planning failed")
            return AgentResult(
                success=False, output="", error=f"Document planning failed: {e}",
                tokens_used=cb_state.tokens_used, cost=cb_state.total_cost,
            )

        doc_format = plan.get("format", "pdf")
        title = plan.get("title", "Document")

        # ── Step 2: Generate the document ──
        try:
            if doc_format == "pptx":
                result = await self._generate_pptx(plan, title)
            elif doc_format == "docx":
                result = self._generate_docx(plan, title)
            elif doc_format == "xlsx":
                result = self._generate_xlsx(plan, title)
            else:
                result = self._generate_pdf(plan, title)
        except Exception as e:
            logger.exception("Document generation failed")
            return AgentResult(
                success=False, output="", error=f"Generation failed: {e}",
                tokens_used=cb_state.tokens_used, cost=cb_state.total_cost,
            )

        file_data, artifacts = result

        return AgentResult(
            success=True,
            output=f"Generated {doc_format.upper()}: {title} ({file_data.size_kb:.1f} KB)",
            artifacts=artifacts,
            tokens_used=cb_state.tokens_used,
            cost=cb_state.total_cost,
        )

    async def _generate_pptx(self, plan: dict, title: str) -> tuple:
        """Generate PPTX with optional AI-generated images."""
        slides_data = plan.get("slides", [])
        if not slides_data:
            slides_data = [{"title": title, "content": "Content placeholder"}]

        # Generate images for slides that have image_prompt
        image_prompts = [s.get("image_prompt", "") for s in slides_data]
        has_prompts = any(p for p in image_prompts)

        slide_images: list[bytes | None] = [None] * len(slides_data)
        if has_prompts:
            topics = [p for p in image_prompts if p]
            generated = await generate_presentation_images(topics)
            img_idx = 0
            for i, prompt in enumerate(image_prompts):
                if prompt and img_idx < len(generated):
                    slide_images[i] = generated[img_idx]
                    img_idx += 1

        # Build slides with images
        formatted_slides = []
        for i, slide in enumerate(slides_data):
            formatted_slides.append({
                "title": slide.get("title", f"Slide {i + 1}"),
                "content": slide.get("content", ""),
                "image_bytes": slide_images[i],
            })

        file_data = generate_pptx(formatted_slides, title=title)

        artifacts = [{
            "type": "file",
            "name": file_data.name,
            "content_b64": base64.b64encode(file_data.content).decode(),
            "mime_type": file_data.mime_type,
            "format": "pptx",
        }]

        return file_data, artifacts

    def _generate_pdf(self, plan: dict, title: str) -> tuple:
        """Generate PDF from sections."""
        sections = plan.get("sections", [])
        content_parts = []
        for section in sections:
            heading = section.get("heading", "")
            body = section.get("content", "")
            if heading:
                content_parts.append(f"## {heading}")
            if body:
                content_parts.append(body)

        content = "\n\n".join(content_parts) if content_parts else plan.get("content", title)

        file_data = generate_pdf(content, title=title)
        artifacts = [{
            "type": "file",
            "name": file_data.name,
            "content_b64": base64.b64encode(file_data.content).decode(),
            "mime_type": file_data.mime_type,
            "format": "pdf",
        }]
        return file_data, artifacts

    def _generate_docx(self, plan: dict, title: str) -> tuple:
        """Generate DOCX from sections."""
        sections = plan.get("sections", [])
        content_parts = []
        for section in sections:
            heading = section.get("heading", "")
            body = section.get("content", "")
            if heading:
                content_parts.append(f"## {heading}")
            if body:
                content_parts.append(body)

        content = "\n\n".join(content_parts) if content_parts else plan.get("content", title)

        file_data = generate_docx(content, title=title)
        artifacts = [{
            "type": "file",
            "name": file_data.name,
            "content_b64": base64.b64encode(file_data.content).decode(),
            "mime_type": file_data.mime_type,
            "format": "docx",
        }]
        return file_data, artifacts

    def _generate_xlsx(self, plan: dict, title: str) -> tuple:
        """Generate Excel from data."""
        data = plan.get("data", [])
        if not data:
            data = [{"Note": "No data provided"}]

        file_data = generate_excel(data, title=title)
        artifacts = [{
            "type": "file",
            "name": file_data.name,
            "content_b64": base64.b64encode(file_data.content).decode(),
            "mime_type": file_data.mime_type,
            "format": "xlsx",
        }]
        return file_data, artifacts

    @staticmethod
    def _parse_json(text: str) -> dict:
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)
        return json.loads(text)
