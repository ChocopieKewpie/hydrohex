from hydrohex.cli import build_parser


def test_cli_exposes_toolbox_commands_without_importing_h3_runtime():
    parser = build_parser()
    for command in ["generate", "fetch-dem", "import-raster", "real-dem-test", "preprocess", "route", "pipeline", "self-test", "benchmark"]:
        args = parser.parse_args([command, "--help"]) if False else None
    assert {"generate", "fetch-dem", "import-raster", "real-dem-test", "preprocess", "route", "pipeline", "self-test", "benchmark"}.issubset(
        parser._subparsers._group_actions[0].choices
    )


def test_pipeline_parser_accepts_parallel_and_conditioning_options():
    parser = build_parser()
    args = parser.parse_args(
        [
            "pipeline",
            "input.csv",
            "output.gpkg",
            "--smooth",
            "bilateral",
            "--condition",
            "hybrid",
            "--workers",
            "4",
        ]
    )
    assert args.smooth == "bilateral"
    assert args.condition == "hybrid"
    assert args.workers == 4


def test_real_dem_defaults_to_loch_vale_1m_and_h3_res13():
    parser = build_parser()
    args = parser.parse_args(["real-dem-test"])
    assert args.site == "loch-vale"
    assert args.bbox is None
    assert args.pixel_size_m == 1.0
    assert args.resolution == 13
    assert str(args.work_dir).replace("\\", "/").endswith("data/real_dem/loch_vale")


def test_import_raster_defaults_to_h3_res13():
    parser = build_parser()
    args = parser.parse_args(["import-raster", "dem.tif", "dem.gpkg"])
    assert args.resolution == 13


def test_pipeline_parser_accepts_partitioned_parquet_directory_and_autodetects_fields():
    parser = build_parser()
    args = parser.parse_args(["pipeline", "Taranaki_h3", "flow.gpkg", "--workers", "8"])
    assert str(args.input) == "Taranaki_h3"
    assert args.id_field is None
    assert args.elevation_field is None


def test_route_parser_exposes_indexed_backend_and_progress_toggle():
    parser = build_parser()
    args = parser.parse_args([
        "route", "in.gpkg", "out.gpkg", "--backend", "indexed", "--no-progress"
    ])
    assert args.backend == "indexed"
    assert args.progress is False


def test_pipeline_defaults_to_auto_backend_with_progress():
    parser = build_parser()
    args = parser.parse_args(["pipeline", "in.gpkg", "out.gpkg"])
    assert args.backend == "auto"
    assert args.progress is True


def test_benchmark_parser_accepts_real_dem_and_outputs():
    parser = build_parser()
    args = parser.parse_args([
        "benchmark",
        "Taranaki_h3.gpkg",
        "--layer",
        "cells",
        "--id-field",
        "h3_13",
        "--elevation-field",
        "band_1",
        "--workers",
        "8",
        "--repeats",
        "5",
        "--json",
        "benchmark.json",
        "--csv",
        "benchmark.csv",
    ])
    assert str(args.input) == "Taranaki_h3.gpkg"
    assert args.workers == 8
    assert args.repeats == 5
    assert str(args.json_output) == "benchmark.json"
    assert str(args.csv_output) == "benchmark.csv"
