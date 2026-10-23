from benchmarks.hsn_benchmark import (
    LIMIT_US,
    Result,
    build_synthetic_records,
    main,
    measure,
    run,
)


def test_synthetic_records_are_unique_8_digit_codes_with_parents():
    records = build_synthetic_records(50)
    codes = [record.code for record in records]
    assert len(codes) == len(set(codes))
    assert sum(len(code) == 8 for code in codes) == 50
    assert any(len(code) == 4 for code in codes)


def test_measure_returns_positive_microseconds():
    assert measure(lambda arg: arg, ["a", "b"], repeat=2) > 0


def test_result_pass_rules():
    assert Result("fast", 10.0, LIMIT_US).passed is True
    assert Result("slow", LIMIT_US + 1, LIMIT_US).passed is False
    assert Result("info", 99999.0, None).passed is True


def test_run_covers_every_scenario():
    results = run(count=200, calls=20)
    assert len(results) == 5
    assert all(result.microseconds > 0 for result in results)
    assert all(result.limit_us == LIMIT_US for result in results[:4])
    assert results[4].limit_us is None


def test_main_prints_a_report(capsys):
    code = main(count=200, calls=20)
    output = capsys.readouterr().out
    assert code in (0, 1)
    assert "description search" in output
    assert "Sub-millisecond target" in output
