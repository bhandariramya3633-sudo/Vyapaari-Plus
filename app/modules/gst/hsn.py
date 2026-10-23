"""HSN/SAC lookup service, fully in memory.

- exact lookup: one dict access.
- longest-known-prefix lookup: a trie walk, so an 8-digit code that is not in
  the data still resolves to its 6- or 4-digit parent.
- code search: a trie walk, results in code order.
- description search: every word must appear in the description.

The bundled dataset is SAMPLE data for development and tests. Load the
official HSN/SAC master with HsnCache(load_records(path)) before real use.
"""

import csv
from collections.abc import Iterable
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.modules.gst.models import HSN_RE, HsnRecord

SAMPLE_DATA_PATH = Path(__file__).parent / "data" / "hsn_sample.csv"
REQUIRED_COLUMNS = ("code", "description", "kind", "gst_rate")


def _clean_code(code) -> str:
    if not isinstance(code, str):
        raise ValidationError(f"code must be a string, not {type(code).__name__}")
    cleaned = code.strip()
    if not HSN_RE.fullmatch(cleaned):
        raise ValidationError(f"code must be 4, 6 or 8 digits: {code!r}")
    return cleaned


class _Node:
    __slots__ = ("children", "record")

    def __init__(self):
        self.children: dict[str, "_Node"] = {}
        self.record: HsnRecord | None = None


class HsnCache:
    """Immutable in-memory index of HSN/SAC records."""

    def __init__(self, records: Iterable[HsnRecord]):
        self._by_code: dict[str, HsnRecord] = {}
        self._root = _Node()
        self._descriptions: list[tuple[str, HsnRecord]] = []
        for record in sorted(records, key=lambda item: item.code):
            if record.code in self._by_code:
                raise ValidationError(f"duplicate HSN/SAC code: {record.code}")
            self._by_code[record.code] = record
            node = self._root
            for digit in record.code:
                node = node.children.setdefault(digit, _Node())
            node.record = record
            self._descriptions.append((record.description.lower(), record))

    def __len__(self) -> int:
        return len(self._by_code)

    def resolve(self, code) -> HsnRecord:
        """Exact record for code, else the longest known parent code."""
        code = _clean_code(code)
        record = self._by_code.get(code)
        if record is not None:
            return record
        node = self._root
        best = None
        for digit in code:
            node = node.children.get(digit)
            if node is None:
                break
            if node.record is not None:
                best = node.record
        if best is None:
            raise EntityNotFoundError("HSN/SAC", code)
        return best

    def rate_for(self, code) -> Decimal:
        """GST rate for code. Usable as the rate_lookup of calculate_invoice."""
        return self.resolve(code).gst_rate

    def search(self, query, limit: int = 20) -> list[HsnRecord]:
        """Digits search by code prefix, anything else by description words."""
        if not isinstance(query, str) or not query.strip():
            raise ValidationError("search query must not be empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValidationError("limit must be a positive integer")
        query = query.strip()
        if query.isascii() and query.isdigit():
            return self._search_code_prefix(query, limit)
        return self._search_description(query, limit)

    def _search_code_prefix(self, prefix: str, limit: int) -> list[HsnRecord]:
        node = self._root
        for digit in prefix:
            node = node.children.get(digit)
            if node is None:
                return []
        found: list[HsnRecord] = []
        stack = [node]
        while stack and len(found) < limit:
            current = stack.pop()
            if current.record is not None:
                found.append(current.record)
            for digit in sorted(current.children, reverse=True):
                stack.append(current.children[digit])
        return found

    def _search_description(self, query: str, limit: int) -> list[HsnRecord]:
        words = query.lower().split()
        found: list[HsnRecord] = []
        for text, record in self._descriptions:
            if all(word in text for word in words):
                found.append(record)
                if len(found) == limit:
                    break
        return found


def _cell(row: dict, key: str) -> str:
    return (row.get(key) or "").strip()


def load_records(path: Path = SAMPLE_DATA_PATH) -> list[HsnRecord]:
    """Read HSN/SAC records from a CSV. Blank lines and # comments are skipped."""
    path = Path(path)
    with open(path, newline="", encoding="utf-8") as handle:
        lines = (
            line for line in handle if line.strip() and not line.lstrip().startswith("#")
        )
        reader = csv.DictReader(lines)
        missing = sorted(set(REQUIRED_COLUMNS) - set(reader.fieldnames or []))
        if missing:
            raise ValidationError(f"{path.name} is missing columns: {', '.join(missing)}")
        return [
            HsnRecord(
                code=_cell(row, "code"),
                description=_cell(row, "description"),
                kind=_cell(row, "kind"),
                gst_rate=_cell(row, "gst_rate"),
                cess_rate=_cell(row, "cess_rate") or "0",
            )
            for row in reader
        ]


@lru_cache(maxsize=1)
def default_cache() -> HsnCache:
    """The cache built from the bundled SAMPLE data, loaded once."""
    return HsnCache(load_records())


def resolve_hsn(code) -> HsnRecord:
    return default_cache().resolve(code)


def search_hsn(query, limit: int = 20) -> list[HsnRecord]:
    return default_cache().search(query, limit)


def hsn_rate(code) -> Decimal:
    return default_cache().rate_for(code)
