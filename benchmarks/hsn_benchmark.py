"""Benchmark for the in-memory HSN/SAC cache.

Run from the repo root:  python -m benchmarks.hsn_benchmark

Timings use the bundled SAMPLE data and a synthetic dataset of 20,000 codes
(about the size of a full HSN/SAC master). Description search scans every
description, so it is reported for information and is not held to the
sub-millisecond limit.
"""

from dataclasses import dataclass
from time import perf_counter_ns

from app.modules.gst.hsn import HsnCache, default_cache
from app.modules.gst.models import HsnRecord

LIMIT_US = 1000.0  # sub-millisecond
FIRST_CODE = 10_000_000
STEP = 3


@dataclass(frozen=True)
class Result:
    name: str
    microseconds: float
    limit_us: float | None

    @property
    def passed(self) -> bool:
        return self.limit_us is None or self.microseconds < self.limit_us


def build_synthetic_records(count: int) -> list[HsnRecord]:
    """8-digit synthetic codes (every STEP-th number) plus their 4-digit parents."""
    records = []
    parents = set()
    for i in range(count):
        code = str(FIRST_CODE + i * STEP)
        records.append(
            HsnRecord(
                code=code,
                description=f"Synthetic item {i}",
                kind="HSN",
                gst_rate="18",
            )
        )
        parents.add(code[:4])
    for parent in sorted(parents):
        records.append(
            HsnRecord(
                code=parent,
                description=f"Synthetic group {parent}",
                kind="HSN",
                gst_rate="18",
            )
        )
    return records


def measure(fn, args, repeat: int = 5) -> float:
    """Best average time per call over several runs, in microseconds."""
    best = float("inf")
    for _ in range(repeat):
        start = perf_counter_ns()
        for arg in args:
            fn(arg)
        per_call = (perf_counter_ns() - start) / len(args)
        best = min(best, per_call)
    return best / 1000.0


def run(count: int = 20_000, calls: int = 2_000) -> list[Result]:
    calls = min(calls, count)
    synthetic = HsnCache(build_synthetic_records(count))
    present = [str(FIRST_CODE + i * STEP) for i in range(calls)]
    absent = [str(FIRST_CODE + i * STEP + 1) for i in range(calls)]
    prefixes = [code[:4] for code in present]
    words = [f"item {i}" for i in range(min(20, calls))]
    sample_codes = ["1006", "8471", "9983", "998314"] * max(1, calls // 4)
    return [
        Result(
            "exact lookup, bundled sample data",
            measure(default_cache().resolve, sample_codes),
            LIMIT_US,
        ),
        Result(
            f"exact lookup, synthetic {count} codes",
            measure(synthetic.resolve, present),
            LIMIT_US,
        ),
        Result(
            "longest-prefix lookup (8-digit code not in data)",
            measure(synthetic.resolve, absent),
            LIMIT_US,
        ),
        Result(
            "code prefix search, limit 20",
            measure(synthetic.search, prefixes),
            LIMIT_US,
        ),
        Result(
            "description search, full scan (info only)",
            measure(synthetic.search, words, repeat=3),
            None,
        ),
    ]


def main(count: int = 20_000, calls: int = 2_000) -> int:
    print("HSN/SAC cache benchmark (best average, microseconds per call)")
    results = run(count, calls)
    for result in results:
        if result.limit_us is None:
            status = "info"
        else:
            status = "PASS" if result.passed else "FAIL"
        print(f"{status:>4}  {result.microseconds:10.2f} us  {result.name}")
    ok = all(result.passed for result in results)
    print(f"Sub-millisecond target (under {LIMIT_US:.0f} us): {'met' if ok else 'NOT met'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
