"""Image generation via Gemini API (Nano Banana 2 / gemini-3.1-flash-image-preview).

Generates images from text prompts using Google's Gemini image generation model.
Cost: ~$0.045-0.15 per image depending on resolution.
"""

import base64
import logging

import httpx

from config.settings import settings

logger = logging.getLogger("agentos.tools.image_generator")

_GEMINI_IMAGE_MODEL = "gemini-2.0-flash-exp"  # Image generation capable model
_GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta"


async def generate_image(
    prompt: str,
    aspect_ratio: str = "16:9",
    style: str = "professional, clean, modern",
) -> bytes | None:
    """Generate an image from a text prompt using Gemini API.

    Args:
        prompt: Description of the image to generate.
        aspect_ratio: Desired aspect ratio (e.g. "16:9", "1:1", "4:3").
        style: Style modifiers appended to the prompt.

    Returns:
        Image bytes (PNG) or None if generation fails.
    """
    if not settings.google_api_key:
        logger.warning("Google API key not configured — skipping image generation")
        return None

    full_prompt = f"{prompt}. Style: {style}. Aspect ratio: {aspect_ratio}"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{_GEMINI_API_URL}/models/{_GEMINI_IMAGE_MODEL}:generateContent",
                params={"key": settings.google_api_key},
                json={
                    "contents": [{"parts": [{"text": full_prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["TEXT", "IMAGE"],
                    },
                },
            )

            if resp.status_code != 200:
                logger.error("Gemini image generation failed: %s %s",
                             resp.status_code, resp.text[:200])
                return None

            data = resp.json()

            # Extract image from response
            candidates = data.get("candidates", [])
            for candidate in candidates:
                parts = candidate.get("content", {}).get("parts", [])
                for part in parts:
                    if "inlineData" in part:
                        b64_data = part["inlineData"].get("data", "")
                        if b64_data:
                            return base64.b64decode(b64_data)

            logger.warning("No image data in Gemini response")
            return None

    except Exception as e:
        logger.exception("Image generation error")
        return None


async def generate_presentation_images(
    slide_topics: list[str],
    style: str = "professional business presentation, flat design, vibrant colors",
) -> list[bytes | None]:
    """Generate images for each slide topic in a presentation.

    Args:
        slide_topics: List of topic descriptions for each slide.
        style: Consistent style for all images.

    Returns:
        List of image bytes (or None for failed generations).
    """
    images = []
    for topic in slide_topics:
        prompt = f"Illustration for a presentation slide about: {topic}"
        img = await generate_image(prompt, aspect_ratio="16:9", style=style)
        images.append(img)
    return images
