import pytest

from coiner.vision import VisionError, _parse_identity


def test_parse_identity_validates_required_and_optional_fields() -> None:
    identity = _parse_identity(
        {
            "country": "France",
            "denomination": "1 franc",
            "year": 1900,
            "mint": None,
            "ruler_or_issuer": "Third Republic",
            "description": None,
        }
    )

    assert identity.search_text() == "France 1 franc 1900 Third Republic"


@pytest.mark.parametrize(
    "data",
    [
        [],
        {"country": "", "denomination": "1 franc"},
        {"country": "France", "denomination": "1 franc", "year": "1900"},
    ],
)
def test_parse_identity_rejects_invalid_response(data: object) -> None:
    with pytest.raises(ValueError):
        _parse_identity(data)
