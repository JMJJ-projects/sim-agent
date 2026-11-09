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

bench:
	python scripts/bench.py run
	python scripts/bench.py promote

bench-status:
	python scripts/bench.py status

report:
	python scripts/report.py

eval-smoke:
	python scripts/evaluate.py --provider fake --mode repair --limit 3 --run-name ci-fake-smoke --results-dir runs/ci-results

# v2 pipeline check: fake provider, 3 tasks x 2 seeds x 2 modes on both task sets, then stats.
# Proves the pipeline end to end; claims nothing about accuracy (PLAN-v2 2.5).
eval-smoke-v2:
	python scripts/evaluate.py --provider fake --mode baseline --task-set all --seeds 0,1 --limit 3 --run-name ci-fake-baseline --results-dir runs/ci-results/v2
	python scripts/evaluate.py --provider fake --mode repair --task-set all --seeds 0,1 --limit 3 --run-name ci-fake-repair --results-dir runs/ci-results/v2
	python scripts/stats_v2.py --results-dir runs/ci-results/v2 --min-seeds 2

api-doc:
	python scripts/gen_api_doc.py

graph-doc:
	python scripts/export_graph.py

materials:
	python scripts/build_materials.py

.PHONY: bench bench-status report eval-smoke eval-smoke-v2 sandbox-image install lint format test test-docker cov check api-doc graph-doc materials
