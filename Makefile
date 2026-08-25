.PHONY: conda-env install test lint self-test dem qgis real-dem-test example qgis-example toolbox-example

conda-env:
	conda env create -f environment.yml

install:
	python -m pip install -e '.[all]'

test:
	pytest

lint:
	ruff check src tests

self-test:
	hydrohex self-test --workers 2

dem:
	hydrohex generate --format csv --output-dir data/generated

qgis:
	hydrohex generate --format gpkg --output-dir data/generated

real-dem-test:
	hydrohex real-dem-test --site loch-vale --work-dir data/real_dem/loch_vale --workers 4

example:
	python examples/basic_h3.py

qgis-example:
	python examples/export_qgis.py

toolbox-example:
	python examples/toolbox_pipeline.py
