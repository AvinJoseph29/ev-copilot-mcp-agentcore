ifeq (,$(wildcard .env))
$(error .env file is missing — copy .env.example to .env)
endif

include .env

# --- Development ---

dev:
	agentcore dev

# --- QA ---

format-fix:
	uv run ruff format .
	uv run ruff check --select I --fix

lint-check:
	uv run ruff check .
