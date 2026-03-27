"""Tests for the Document agent and file generation tools."""

import io

import pytest
from unittest.mock import patch, MagicMock

from tools.file_generator import (
    GeneratedFile,
    generate_docx,
    generate_excel,
    generate_pdf,
    generate_pptx,
)


# ─── File Generator ──────────────────────────────────────────────────────

class TestGeneratePDF:

    def test_basic_pdf(self):
        result = generate_pdf("Hello world\n\nThis is a test.", title="Test PDF")
        assert isinstance(result, GeneratedFile)
        assert result.format == "pdf"
        assert result.name == "Test_PDF.pdf"
        assert len(result.content) > 100
        assert result.content[:5] == b"%PDF-"

    def test_pdf_with_headings(self):
        content = "# Heading 1\n\nSome text.\n\n## Heading 2\n\nMore text."
        result = generate_pdf(content, title="Headings")
        assert result.size_kb > 0

    def test_pdf_special_chars(self):
        result = generate_pdf("Price: $100 < $200 & more > less", title="Special")
        assert result.format == "pdf"


class TestGeneratePPTX:

    def test_basic_pptx(self):
        slides = [
            {"title": "Title Slide", "content": "Welcome"},
            {"title": "Slide 2", "content": "Point 1\nPoint 2\nPoint 3"},
        ]
        result = generate_pptx(slides, title="Test Pres")
        assert result.format == "pptx"
        assert result.name == "Test_Pres.pptx"
        assert len(result.content) > 100

    def test_pptx_validates_as_zip(self):
        """PPTX files are ZIP archives."""
        import zipfile
        slides = [{"title": "Test", "content": "Content"}]
        result = generate_pptx(slides)
        buf = io.BytesIO(result.content)
        assert zipfile.is_zipfile(buf)

    def test_empty_slides(self):
        result = generate_pptx([], title="Empty")
        assert result.format == "pptx"


class TestGenerateDOCX:

    def test_basic_docx(self):
        result = generate_docx("Hello world\n\nSecond paragraph.", title="Test Doc")
        assert result.format == "docx"
        assert result.name == "Test_Doc.docx"
        assert len(result.content) > 100

    def test_docx_with_headings_and_lists(self):
        content = "# Introduction\n\nSome text.\n\n- Item 1\n- Item 2\n\n## Details\n\nMore text."
        result = generate_docx(content, title="Formatted")
        assert result.size_kb > 0


class TestGenerateExcel:

    def test_basic_excel(self):
        data = [
            {"Name": "Alice", "Score": 95},
            {"Name": "Bob", "Score": 87},
        ]
        result = generate_excel(data, title="Scores")
        assert result.format == "xlsx"
        assert result.name == "Scores.xlsx"
        assert len(result.content) > 100

    def test_multi_sheet(self):
        sheets = {
            "Sales": [{"Q": "Q1", "Amount": 100}, {"Q": "Q2", "Amount": 200}],
            "Costs": [{"Q": "Q1", "Amount": 50}],
        }
        result = generate_excel([], sheets=sheets, title="Report")
        assert result.format == "xlsx"

    def test_empty_data(self):
        result = generate_excel([], title="Empty")
        assert result.format == "xlsx"


# ─── Document Parser ─────────────────────────────────────────────────────

class TestDocumentParser:

    def test_parsed_document_success(self):
        from tools.document_parser import ParsedDocument
        doc = ParsedDocument(text="hello")
        assert doc.success

    def test_parsed_document_failure(self):
        from tools.document_parser import ParsedDocument
        doc = ParsedDocument(error="parse failed")
        assert not doc.success

    def test_unsupported_format(self):
        from tools.document_parser import parse_document
        result = parse_document("file.xyz")
        assert not result.success


# ─── Image Generator ─────────────────────────────────────────────────────

class TestImageGenerator:

    @pytest.mark.asyncio
    async def test_no_api_key(self):
        from unittest.mock import patch
        with patch("tools.image_generator.settings") as mock:
            mock.google_api_key = ""
            from tools.image_generator import generate_image
            result = await generate_image("a cat")
            assert result is None


# ─── Document Agent ──────────────────────────────────────────────────────

class TestDocumentAgent:

    def test_model_selection_simple(self):
        from agents.document import DocumentAgent
        mock = MagicMock()
        mock.qwen_api_key = "qwen-key-test"
        mock.kimi_api_key = "kimi-key-test"
        with patch("config.model_router.settings", mock):
            agent = DocumentAgent()
            assert agent._select_model("simple template for a list") == "agentOS/cheap-qwen"

    def test_model_selection_standard(self):
        from agents.document import DocumentAgent
        mock = MagicMock()
        mock.qwen_api_key = "qwen-key-test"
        mock.kimi_api_key = "kimi-key-test"
        with patch("config.model_router.settings", mock):
            agent = DocumentAgent()
            assert agent._select_model("create a presentation about AI") == "agentOS/workhorse-qwen"


# ─── Integration ──────────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_document_agent_pptx():
    """Full flow: generate a 5-slide presentation."""
    from agents.document import DocumentAgent

    agent = DocumentAgent()
    result = await agent.execute(
        task={
            "goal": "Crea una presentación de 5 slides sobre AgentOS con imágenes",
            "task_id": "test-doc-001",
        },
        context={},
    )

    assert result.success or result.error is not None
    if result.success:
        pptx_artifacts = [a for a in result.artifacts if a.get("format") == "pptx"]
        assert len(pptx_artifacts) > 0
