.PHONY: format
format:
	venv/bin/ruff format --target-version py37 .

.PHONY: ck-format
ck-format:
	venv/bin/ruff format --check --target-version py37 .
