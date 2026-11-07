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

api-doc:
	python scripts/gen_api_doc.py

materials:
	python scripts/build_materials.py

.PHONY: sandbox-image install lint format test test-docker cov check api-doc materials
