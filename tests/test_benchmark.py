from pathlib import Path

from hydrohex.benchmark import (
    benchmark_d6_backends,
    write_benchmark_csv,
    write_benchmark_json,
)


def test_benchmark_matches_backends_and_writes_outputs(tmp_path: Path):
    # A tiny graph with one unambiguous downslope receiver per non-sink cell.
    elevation = {"a": 3.0, "b": 2.0, "c": 1.0}
    adjacency = {"a": ("b",), "b": ("a", "c"), "c": ("b",)}
    coords = {"a": (0.0, 0.0), "b": (0.0, 0.001), "c": (0.0, 0.002)}

    result = benchmark_d6_backends(
        elevation,
        lambda cell: adjacency[cell],
        lambda _a, _b: 1.0,
        lambda cell: coords[cell],
        workers=1,
        repeats=2,
        warmup=0,
        source="unit-test",
    )

    assert result.cells == 3
    assert result.equivalent_receivers is True
    assert len(result.python_times_s) == 2
    assert len(result.indexed_times_s) == 2
    assert result.python_median_s >= 0.0
    assert result.indexed_median_s >= 0.0

    json_path = write_benchmark_json(tmp_path / "benchmark.json", result)
    csv_path = write_benchmark_csv(tmp_path / "benchmark.csv", result)
    assert '"equivalent_receivers": true' in json_path.read_text()
    assert "routing_speedup" in csv_path.read_text().splitlines()[0]
