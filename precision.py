"""
Helpers that make DDGS searches more precise.

Search engines treat a free-form address like "265 South Street Manhattan NY 10004"
as a bag of words, so results drift to anything mentioning "South", "Manhattan",
or "10004". These helpers split a US street address into parts, build a query
that quotes the street line, and filter results down to ones that mention it.
"""
import re
from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional

# Canonical street suffix -> accepted spellings (USPS Publication 28 subset).
STREET_SUFFIXES: Dict[str, set] = {
    "street": {"street", "st", "str"},
    "avenue": {"avenue", "ave", "av"},
    "boulevard": {"boulevard", "blvd"},
    "road": {"road", "rd"},
    "drive": {"drive", "dr"},
    "lane": {"lane", "ln"},
    "place": {"place", "pl"},
    "court": {"court", "ct"},
    "terrace": {"terrace", "ter"},
    "parkway": {"parkway", "pkwy"},
    "highway": {"highway", "hwy"},
    "square": {"square", "sq"},
    "plaza": {"plaza", "plz"},
    "circle": {"circle", "cir"},
    "way": {"way"},
    "slip": {"slip"},
    "row": {"row"},
    "alley": {"alley", "aly"},
    "expressway": {"expressway", "expy"},
    "turnpike": {"turnpike", "tpke"},
}

DIRECTIONALS: Dict[str, set] = {
    "north": {"north", "n"},
    "south": {"south", "s"},
    "east": {"east", "e"},
    "west": {"west", "w"},
    "northeast": {"northeast", "ne"},
    "northwest": {"northwest", "nw"},
    "southeast": {"southeast", "se"},
    "southwest": {"southwest", "sw"},
}

# Standard USPS abbreviation for each canonical suffix.
SUFFIX_ABBREVIATIONS: Dict[str, str] = {
    "street": "St", "avenue": "Ave", "boulevard": "Blvd", "road": "Rd", "drive": "Dr",
    "lane": "Ln", "place": "Pl", "court": "Ct", "terrace": "Ter", "parkway": "Pkwy",
    "highway": "Hwy", "square": "Sq", "plaza": "Plz", "circle": "Cir", "way": "Way",
    "slip": "Slip", "row": "Row", "alley": "Aly", "expressway": "Expy", "turnpike": "Tpke",
}

_CANONICAL = {
    variant: canonical
    for table in (STREET_SUFFIXES, DIRECTIONALS)
    for canonical, variants in table.items()
    for variant in variants
}
_SUFFIX_WORDS = {variant for variants in STREET_SUFFIXES.values() for variant in variants}
_SUFFIX_CANONICAL = {
    variant: canonical
    for canonical, variants in STREET_SUFFIXES.items()
    for variant in variants
}

US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "PR": "Puerto Rico",
}
_STATE_NAMES = {name.lower(): code for code, name in US_STATES.items()}

_NUMBER_RE = re.compile(r"^\s*(\d+[A-Za-z]?(?:-\d+[A-Za-z]?)?)\s+(.+?)\s*$")
_ZIP_RE = re.compile(r"[\s,]*(\d{5}(?:-\d{4})?)\s*$")
_QUOTED_RE = re.compile(r'"([^"]+)"')
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class ParsedAddress:
    number: str
    street: str
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None

    @property
    def street_line(self) -> str:
        return f"{self.number} {self.street}"

    def to_dict(self) -> Dict[str, Optional[str]]:
        data = asdict(self)
        data["street_line"] = self.street_line
        return data


def _strip_state(text: str) -> tuple[str, Optional[str]]:
    """Remove a trailing state code or full state name. Returns (rest, code)."""
    text = text.rstrip(" ,")
    lowered = text.lower()
    for name, code in sorted(_STATE_NAMES.items(), key=lambda item: -len(item[0])):
        if lowered.endswith(name) and (len(lowered) == len(name) or not lowered[-len(name) - 1].isalnum()):
            return text[: -len(name)].rstrip(" ,"), code
    match = re.search(r"[\s,]([A-Za-z]{2})\.?$", text)
    if match and match.group(1).upper() in US_STATES:
        return text[: match.start()].rstrip(" ,"), match.group(1).upper()
    return text, None


def parse_us_address(address: str) -> Optional[ParsedAddress]:
    """
    Split a US street address into number, street, city, state, and ZIP.

    Commas are optional: "265 South Street Manhattan NY 10004" and
    "265 South St, Manhattan, NY 10004" both parse. Without commas the street
    ends at the last suffix word (Street, Ave, Blvd, ...). Returns None when the
    text does not start with a house number.
    """
    match = _NUMBER_RE.match(address or "")
    if not match:
        return None
    number, rest = match.group(1), match.group(2)

    zip_code = None
    zip_match = _ZIP_RE.search(rest)
    if zip_match:
        zip_code = zip_match.group(1)
        rest = rest[: zip_match.start()]

    rest, state = _strip_state(rest)

    if "," in rest:
        street, _, city = rest.partition(",")
    else:
        words = rest.split()
        suffix_positions = [
            idx for idx, word in enumerate(words)
            if idx > 0 and word.lower().rstrip(".") in _SUFFIX_WORDS
        ]
        if suffix_positions:
            end = suffix_positions[-1] + 1
            # Keep a trailing directional such as "Main St NW".
            if end < len(words) and words[end].lower() in {"n", "s", "e", "w", "ne", "nw", "se", "sw"}:
                end += 1
        else:
            # Suffixless streets ("25 Broadway"): assume a single word.
            end = 1
        street, city = " ".join(words[:end]), " ".join(words[end:])

    street = street.strip(" ,")
    city = city.strip(" ,") or None
    if not street:
        return None
    return ParsedAddress(number=number, street=street, city=city, state=state, zip_code=zip_code)


def _restyle_street(street: str, abbreviate: bool) -> str:
    """Rewrite suffix words (never the first word, e.g. "St Marks Pl") in full or abbreviated form."""
    words = street.split()
    for idx in range(1, len(words)):
        canonical = _SUFFIX_CANONICAL.get(words[idx].lower().rstrip("."))
        if canonical:
            words[idx] = SUFFIX_ABBREVIATIONS[canonical] if abbreviate else canonical.title()
    return " ".join(words)


def expand_street(street: str) -> str:
    """'South St' -> 'South Street'. Search engines match the spelled-out form more reliably."""
    return _restyle_street(street, abbreviate=False)


def abbreviate_street(street: str) -> str:
    """'South Street' -> 'South St'."""
    return _restyle_street(street, abbreviate=True)


def normalize_text(text: str) -> str:
    """Lowercase, drop punctuation, and canonicalize suffixes and directionals."""
    tokens = _NON_ALNUM_RE.sub(" ", (text or "").lower()).split()
    return " " + " ".join(_CANONICAL.get(token, token) for token in tokens) + " "


def build_address_query(
    address: ParsedAddress,
    extra: Optional[str] = None,
    abbreviate: bool = False,
) -> str:
    """
    Quote the street line and add the city and state as loose context.

    The suffix is spelled out by default ("265 South Street"), which matched far
    more reliably than "265 South St" in testing; `abbreviate=True` builds the
    fallback form. The ZIP is left out on purpose: news rarely prints it, and it
    pulled in unrelated listings that share the ZIP.
    """
    street = abbreviate_street(address.street) if abbreviate else expand_street(address.street)
    parts = [f'"{address.number} {street}"']
    if address.city:
        parts.append(address.city)
    if address.state:
        parts.append(address.state)
    if extra:
        parts.append(extra.strip())
    return " ".join(part for part in parts if part)


def required_phrases(query: str) -> List[str]:
    """Quoted phrases in a query, which strict mode requires in every result."""
    return [phrase.strip() for phrase in _QUOTED_RE.findall(query or "") if phrase.strip()]


def matches_all(texts: Iterable[str], phrases: Iterable[str]) -> bool:
    """True when every phrase appears (normalized) in the combined texts."""
    haystack = normalize_text(" ".join(text for text in texts if text))
    return all(normalize_text(phrase) in haystack for phrase in phrases)


def matching_phrases(texts: Iterable[str], phrases: Iterable[str]) -> List[str]:
    """The phrases that appear (normalized) in the combined texts."""
    haystack = normalize_text(" ".join(text for text in texts if text))
    return [phrase for phrase in phrases if normalize_text(phrase) in haystack]
