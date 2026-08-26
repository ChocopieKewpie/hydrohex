from __future__ import annotations

"""Run the same D6 backend benchmark exposed by ``hydrohex benchmark``."""

from hydrohex.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["benchmark"]))
