.PHONY: format
format:
	venv/bin/black -t py35 -t py36 -t py37 -t py38 -t py39 -t py310 -t py311 -t py312 .

.PHONY: ck-format
ck-format:
	venv/bin/black --check .
