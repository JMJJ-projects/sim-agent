install:
	python -m pip install -e ".[dev,ollama]"

lint:
	ruff check .
	ruff format --check .
	mypy src

format:
	ruff format .
	ruff check --fix .

test:
	pytest -q

test-docker:
	pytest -q -m docker

cov:
	pytest -q --cov=src --cov-report=term-missing

check: lint test

sandbox-image:
	docker build -f sandbox/Dockerfile -t simagent-sandbox .

eval-smoke:
	python scripts/evaluate.py --provider fake --mode repair --limit 3 --run-name ci-fake-smoke --results-dir runs/ci-results

api-doc:
	python scripts/gen_api_doc.py

graph-doc:
	python scripts/export_graph.py

materials:
	python scripts/build_materials.py

.PHONY: eval-smoke sandbox-image install lint format test test-docker cov check api-doc graph-doc materials
