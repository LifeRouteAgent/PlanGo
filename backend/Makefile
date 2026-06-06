.PHONY: lint format test

lint:
	python -m ruff check app tests
	python -m mypy

format:
	python -m ruff format app tests
	python -m ruff check --fix app tests

test:
	python -m pytest -q
