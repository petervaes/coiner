import json

import pytest

from coiner.vision import VisionError
from coiner.vision_inspection import inspect_coin_images


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        content = {
            "country": "France",
            "denomination": "1 franc",
            "year": 1935,
            "mint": None,
            "ruler_or_issuer": "French Republic",
            "description": "Morlon",
            "condition": "VF",
            "condition_notes": "Wear is visible on the high points.",
        }
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(content)}}]}
        ).encode()


def test_inspection_sends_both_images_and_parses_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    captured: dict[str, object] = {}

    def fake_urlopen(request: object, timeout: int) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("coiner.vision_inspection.urlopen", fake_urlopen)

    result = inspect_coin_images(
        [("image/jpeg", b"front"), ("image/png", b"back")]
    )

    request = captured["request"]
    payload = json.loads(request.data)
    image_items = [
        item
        for item in payload["messages"][1]["content"]
        if item["type"] == "image_url"
    ]
    assert len(image_items) == 2
    assert request.get_header("Authorization") == "Bearer test-key"
    assert result.identity.year == 1935
    assert result.condition == "VF"
    assert result.condition_notes == "Wear is visible on the high points."


@pytest.mark.parametrize(
    ("images", "message"),
    [
        ([], "one or two"),
        ([("text/plain", b"not an image")], "JPEG, PNG, WEBP, or GIF"),
        ([("image/jpeg", b"")], "empty"),
    ],
)
def test_inspection_validates_uploaded_images(
    monkeypatch: pytest.MonkeyPatch,
    images: list[tuple[str, bytes]],
    message: str,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    with pytest.raises(VisionError, match=message):
        inspect_coin_images(images)


def test_inspection_requires_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(VisionError, match="OPENAI_API_KEY"):
        inspect_coin_images([("image/jpeg", b"valid-image-bytes")])
