from decimal import Decimal

import pytest

from app.core.exceptions import EntityNotFoundError, ValidationError
from app.modules.gst.hsn import (
    SAMPLE_DATA_PATH,
    HsnCache,
    default_cache,
    hsn_rate,
    load_records,
    resolve_hsn,
    search_hsn,
)
from app.modules.gst.models import HsnRecord

HEADER = "code,description,kind,gst_rate,cess_rate\n"


def rec(code, description, kind="HSN", rate="18", cess="0"):
    return HsnRecord(
        code=code, description=description, kind=kind, gst_rate=rate, cess_rate=cess
    )


def make_records():
    return [
        rec("1006", "Rice", rate="5"),
        rec("100610", "Rice in the husk (paddy)", rate="0"),
        rec("10061010", "Seed rice", rate="0"),
        rec("2402", "Cigarettes of tobacco", rate="28", cess="5"),
        rec("8471", "Computers"),
        rec("9983", "Other professional services", kind="SAC"),
        rec("998314", "IT design and development services", kind="SAC"),
    ]


@pytest.fixture
def cache():
    return HsnCache(make_records())


def write_csv(tmp_path, text):
    path = tmp_path / "hsn.csv"
    path.write_text(text, encoding="utf-8")
    return path


# ---------- HsnCache: building ----------


def test_cache_size(cache):
    assert len(cache) == 7


def test_empty_cache_has_nothing_to_find():
    empty = HsnCache([])
    assert len(empty) == 0
    with pytest.raises(EntityNotFoundError):
        empty.resolve("1006")


def test_duplicate_codes_are_rejected():
    with pytest.raises(ValidationError, match="duplicate HSN/SAC code: 1006"):
        HsnCache([rec("1006", "Rice"), rec("1006", "Rice again")])


# ---------- HsnCache: resolve ----------


def test_resolve_exact_code(cache):
    record = cache.resolve("1006")
    assert record.description == "Rice"
    assert record.gst_rate == Decimal("5")


def test_resolve_strips_whitespace(cache):
    assert cache.resolve(" 1006 ").code == "1006"


@pytest.mark.parametrize(
    "code, expected",
    [
        ("10061090", "100610"),
        ("10069000", "1006"),
        ("99831499", "998314"),
        ("99839999", "9983"),
        ("10061010", "10061010"),
    ],
)
def test_resolve_falls_back_to_the_longest_known_parent(cache, code, expected):
    assert cache.resolve(code).code == expected


def test_resolve_unknown_code(cache):
    with pytest.raises(EntityNotFoundError) as exc:
        cache.resolve("5555")
    assert exc.value.code == "NOT_FOUND"


@pytest.mark.parametrize("code", ["12", "abcd", "123456789", "", 1006, None])
def test_resolve_rejects_invalid_codes(cache, code):
    with pytest.raises(ValidationError):
        cache.resolve(code)


def test_rate_for(cache):
    assert cache.rate_for("1006") == Decimal("5")
    assert cache.rate_for("10061090") == Decimal("0")
    assert cache.resolve("2402").cess_rate == Decimal("5")


# ---------- HsnCache: search ----------


def test_search_by_code_prefix_returns_codes_in_order(cache):
    codes = [record.code for record in cache.search("1006")]
    assert codes == ["1006", "100610", "10061010"]


def test_search_by_short_prefix(cache):
    assert [r.code for r in cache.search("99")] == ["9983", "998314"]
    assert [r.code for r in cache.search("1")] == ["1006", "100610", "10061010"]


def test_search_prefix_without_a_record_of_its_own(cache):
    assert [r.code for r in cache.search("10061")] == ["100610", "10061010"]


def test_search_prefix_respects_the_limit(cache):
    assert [r.code for r in cache.search("1006", limit=2)] == ["1006", "100610"]


def test_search_prefix_with_no_match(cache):
    assert cache.search("7777") == []


def test_search_by_description_words(cache):
    assert [r.code for r in cache.search("rice")] == ["1006", "100610", "10061010"]
    assert [r.code for r in cache.search("design services")] == ["998314"]
    assert [r.code for r in cache.search("rice husk")] == ["100610"]


def test_description_search_ignores_case(cache):
    assert [r.code for r in cache.search("RICE")] == [r.code for r in cache.search("rice")]


def test_description_search_respects_the_limit(cache):
    assert [r.code for r in cache.search("rice", limit=1)] == ["1006"]


def test_description_search_with_no_match(cache):
    assert cache.search("zzz") == []


def test_results_are_sorted_by_code_whatever_the_input_order():
    shuffled = HsnCache(reversed(make_records()))
    assert [r.code for r in shuffled.search("rice")] == ["1006", "100610", "10061010"]


@pytest.mark.parametrize("query", ["", "   ", None, 1006])
def test_search_rejects_empty_queries(cache, query):
    with pytest.raises(ValidationError, match="must not be empty"):
        cache.search(query)


@pytest.mark.parametrize("limit", [0, -1, True, "5", 2.5])
def test_search_rejects_invalid_limits(cache, limit):
    with pytest.raises(ValidationError, match="limit must be a positive integer"):
        cache.search("rice", limit=limit)


# ---------- load_records ----------


def test_load_records_skips_comments_and_blank_lines(tmp_path):
    path = write_csv(
        tmp_path,
        "# a comment\n\n" + HEADER + "1006,Rice,HSN,5,0\n\n# another\n"
        "9983,Other services,SAC,18,0\n",
    )
    records = load_records(path)
    assert [r.code for r in records] == ["1006", "9983"]
    assert records[0].gst_rate == Decimal("5")


def test_load_records_cess_column_is_optional(tmp_path):
    path = write_csv(tmp_path, "code,description,kind,gst_rate\n1006,Rice,HSN,5\n")
    assert load_records(path)[0].cess_rate == Decimal("0")


def test_load_records_empty_cess_means_zero(tmp_path):
    path = write_csv(tmp_path, HEADER + "1006,Rice,HSN,5,\n")
    assert load_records(path)[0].cess_rate == Decimal("0")


def test_load_records_keeps_a_cess_value(tmp_path):
    path = write_csv(tmp_path, HEADER + "2402,Cigarettes,HSN,28,5\n")
    assert load_records(path)[0].cess_rate == Decimal("5")


def test_load_records_reports_missing_columns(tmp_path):
    path = write_csv(tmp_path, "code,description\n1006,Rice\n")
    with pytest.raises(ValidationError, match="missing columns: gst_rate, kind"):
        load_records(path)


def test_load_records_comment_only_file(tmp_path):
    path = write_csv(tmp_path, "# nothing here\n")
    with pytest.raises(ValidationError, match="missing columns"):
        load_records(path)


def test_load_records_rejects_invalid_rows(tmp_path):
    path = write_csv(tmp_path, HEADER + "1006,Rice,SAC,5,0\n")
    with pytest.raises(ValidationError, match="services need a SAC"):
        load_records(path)


def test_load_records_rejects_short_rows(tmp_path):
    path = write_csv(tmp_path, HEADER + "1006,Rice\n")
    with pytest.raises(ValidationError):
        load_records(path)


# ---------- bundled sample data ----------


def test_sample_data_is_labelled_as_sample():
    text = SAMPLE_DATA_PATH.read_text(encoding="utf-8")
    assert text.lstrip().upper().startswith("# SAMPLE DATA")


def test_default_cache_is_loaded_once_from_the_sample_data():
    first = default_cache()
    assert default_cache() is first
    assert len(first) > 0


def test_default_cache_helpers():
    assert resolve_hsn("1006").code == "1006"
    assert "1006" in [record.code for record in search_hsn("rice")]
    assert hsn_rate("1006") == Decimal("5")
    assert resolve_hsn("99831499").code == "998314"
