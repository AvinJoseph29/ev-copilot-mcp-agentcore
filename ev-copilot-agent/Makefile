.PHONY: format-fix lint-fix run

format-fix:
	uv run ruff format .

lint-fix:
	uv run ruff check --fix .

run:
	uv run opentelemetry-instrument python -m src.main
