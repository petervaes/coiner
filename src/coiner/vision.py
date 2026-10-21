import base64
import json
import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from coiner.models import CoinIdentity

load_dotenv()

MAX_IMAGE_BYTES = 20 * 1024 * 1024
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"


class VisionError(RuntimeError):
    pass


def identify_coin(image_path: Path) -> CoinIdentity:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise VisionError("OPENAI_API_KEY is not set")

    if not image_path.is_file():
        raise VisionError(f"Image file does not exist: {image_path}")
    image_size = image_path.stat().st_size
    if image_size == 0:
        raise VisionError("Image file is empty")
    if image_size > MAX_IMAGE_BYTES:
        raise VisionError("Image exceeds the 20 MB size limit")

    mime_type, _ = mimetypes.guess_type(image_path.name)
    if mime_type not in SUPPORTED_IMAGE_TYPES:
        raise VisionError("Image must be JPEG, PNG, WEBP, or GIF")

    encoded_image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"),
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "Identify the coin visible in the image. Return only a JSON object "
                    "with country and denomination as required strings, year as an "
                    "integer or null, and mint, ruler_or_issuer, and description as "
                    "strings or null. Do not guess uncertain details; use null."
                ),
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Identify the coin. If both sides are not visible, state "
                            "only what can be supported by this image."
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{encoded_image}",
                        },
                    },
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
        return _parse_identity(data)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError, ValueError) as exc:
        raise VisionError(f"OpenAI returned an invalid coin identification: {exc}") from exc


def _parse_identity(data: object) -> CoinIdentity:
    if not isinstance(data, dict):
        raise ValueError("response must be a JSON object")
    country = data.get("country")
    denomination = data.get("denomination")
    if not isinstance(country, str) or not country.strip():
        raise ValueError("country must be a non-empty string")
    if not isinstance(denomination, str) or not denomination.strip():
        raise ValueError("denomination must be a non-empty string")

    year = data.get("year")
    if year is not None and (not isinstance(year, int) or isinstance(year, bool)):
        raise ValueError("year must be an integer or null")

    optional_fields = ("mint", "ruler_or_issuer", "description")
    for field in optional_fields:
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be a string or null")

    return CoinIdentity(
        country=country.strip(),
        denomination=denomination.strip(),
        year=year,
        mint=data.get("mint"),
        ruler_or_issuer=data.get("ruler_or_issuer"),
        description=data.get("description"),
    )
