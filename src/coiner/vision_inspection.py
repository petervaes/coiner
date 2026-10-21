import base64
import json
import os
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from coiner.models import CoinAssessment
from coiner.vision import (
    MAX_IMAGE_BYTES,
    OPENAI_CHAT_COMPLETIONS_URL,
    SUPPORTED_IMAGE_TYPES,
    VisionError,
    _parse_identity,
)

load_dotenv()


def inspect_coin_images(images: Sequence[tuple[str, bytes]]) -> CoinAssessment:
    if not 1 <= len(images) <= 2:
        raise VisionError("Upload one or two coin images")

    image_contents: list[dict[str, object]] = []
    for mime_type, image_bytes in images:
        if mime_type not in SUPPORTED_IMAGE_TYPES:
            raise VisionError("Image must be JPEG, PNG, WEBP, or GIF")
        if not image_bytes:
            raise VisionError("Image file is empty")
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise VisionError("Image exceeds the 20 MB size limit")
        encoded_image = base64.b64encode(image_bytes).decode("ascii")
        image_contents.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{encoded_image}"},
            }
        )

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise VisionError("OPENAI_API_KEY is not set")

    count = len(images)
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Identify the coin visible in the image. Return only a JSON object "
                    "with country and denomination as required strings, year as an "
                    "integer or null, mint, ruler_or_issuer, and description as strings "
                    "or null, condition as a short grade string, and condition_notes "
                    "as a string or null. Do not guess uncertain details; use null. "
                    "Grade conservatively and do not claim professional certification."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Inspect this coin using the {count} uploaded image"
                            f"{'s' if count > 1 else ''}. Assess visible wear and use "
                            "a familiar grade (G, VG, F, VF, XF, AU, UNC or B, TB, "
                            "TTB, SUP, SPL, FDC). If uncertain, explain that in "
                            "condition_notes."
                        ),
                    },
                    *image_contents,
                ],
            },
        ],
    }
    request = Request(
        OPENAI_CHAT_COMPLETIONS_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise VisionError(f"OpenAI API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise VisionError(f"Could not reach the OpenAI API: {exc.reason}") from exc
    except (json.JSONDecodeError, TimeoutError) as exc:
        raise VisionError(f"Could not read the OpenAI API response: {exc}") from exc

    try:
        content = result["choices"][0]["message"]["content"]
        data = json.loads(content)
        if not isinstance(data, dict):
            raise ValueError("response must be a JSON object")
        identity = _parse_identity(data)
        condition = data.get("condition")
        condition_notes = data.get("condition_notes")
        if not isinstance(condition, str) or not condition.strip():
            raise ValueError("condition must be a non-empty string")
        if condition_notes is not None and not isinstance(condition_notes, str):
            raise ValueError("condition_notes must be a string or null")
        return CoinAssessment(
            identity=identity,
            condition=condition.strip(),
            condition_notes=condition_notes,
        )
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise VisionError(f"OpenAI returned an invalid coin identification: {exc}") from exc
