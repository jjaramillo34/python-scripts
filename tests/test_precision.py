import pytest

from precision import build_address_query, matches_all, parse_us_address, required_phrases


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "265 South Street Manhattan NY 10004",
            {"number": "265", "street": "South Street", "city": "Manhattan", "state": "NY", "zip_code": "10004"},
        ),
        (
            "265 South St, Manhattan, NY 10004",
            {"number": "265", "street": "South St", "city": "Manhattan", "state": "NY", "zip_code": "10004"},
        ),
        (
            "1600 Pennsylvania Ave NW Washington DC 20500",
            {"number": "1600", "street": "Pennsylvania Ave NW", "city": "Washington", "state": "DC", "zip_code": "20500"},
        ),
        (
            "25 Broadway New York NY",
            {"number": "25", "street": "Broadway", "city": "New York", "state": "NY", "zip_code": None},
        ),
        (
            "123 Main St Springfield Illinois 62701-1234",
            {"number": "123", "street": "Main St", "city": "Springfield", "state": "IL", "zip_code": "62701-1234"},
        ),
    ],
)
def test_parse_us_address(raw, expected):
    parsed = parse_us_address(raw)
    assert parsed is not None
    for key, value in expected.items():
        assert getattr(parsed, key) == value


def test_parse_rejects_text_without_house_number():
    assert parse_us_address("South Street Manhattan") is None
    assert parse_us_address("") is None


def test_build_address_query_quotes_street_and_drops_zip():
    parsed = parse_us_address("265 South Street Manhattan NY 10004")
    assert build_address_query(parsed) == '"265 South Street" Manhattan NY'
    assert build_address_query(parsed, "construction") == '"265 South Street" Manhattan NY construction'


def test_matches_all_normalizes_abbreviations_and_slugs():
    assert matches_all(["NEW YORK | 265 South St. tower"], ["265 South Street"])
    assert matches_all(["https://example.com/265-south-st-nyc"], ["265 South Street"])
    assert matches_all(["1600 Pennsylvania Avenue Northwest"], ["1600 Pennsylvania Ave NW"])
    assert not matches_all(["2650 South Street"], ["265 South Street"])
    assert not matches_all(["265 North Street"], ["265 South Street"])


def test_required_phrases():
    assert required_phrases('"265 South Street" tower "Two Bridges"') == ["265 South Street", "Two Bridges"]
    assert required_phrases("no quotes") == []


def test_expand_and_abbreviate_street():
    from precision import abbreviate_street, expand_street

    assert expand_street("South St") == "South Street"
    assert expand_street("Pennsylvania Ave NW") == "Pennsylvania Avenue NW"
    assert expand_street("St Marks Pl") == "St Marks Place"
    assert abbreviate_street("South Street") == "South St"


def test_address_query_spells_out_suffix_with_abbreviated_fallback():
    parsed = parse_us_address("265 South St, New York, NY 10004")
    assert build_address_query(parsed) == '"265 South Street" New York NY'
    assert build_address_query(parsed, abbreviate=True) == '"265 South St" New York NY'
