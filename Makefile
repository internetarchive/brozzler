# Build constants
PYTHON_VERSION = 3.12
VIRTUAL_ENV_DIR = .venv
BROZZLER_EGG_LINK = ./brozzler.egg-info
# Where's the Makefile running? Valid options: LOCAL, CI
ENV ?= LOCAL
# Which package manager to use? Valid options: UV, PIP
PACKAGE_MANAGER ?= UV

$(VIRTUAL_ENV_DIR):
ifeq ($(PACKAGE_MANAGER),UV)
	uv venv -p python$(PYTHON_VERSION) $@
else ifeq ($(PACKAGE_MANAGER),PIP)
	python$(PYTHON_VERSION) -m venv $@
endif

.PHONY: venv
venv: $(VIRTUAL_ENV_DIR)

$(BROZZLER_EGG_LINK): $(VIRTUAL_ENV_DIR) pyproject.toml
ifeq ($(PACKAGE_MANAGER),UV)
	VIRTUAL_ENV=$(shell pwd)/$(VIRTUAL_ENV_DIR) uv build
else ifeq ($(PACKAGE_MANAGER),PIP)
	VIRTUAL_ENV=$(shell pwd)/$(VIRTUAL_ENV_DIR) pip$(PYTHON_VERSION) wheel --no-deps --wheel-dir dist .
endif

.PHONY: build
build: $(BROZZLER_EGG_LINK)

.PHONY: clean
clean: $(BROZZLER_EGG_LINK)
	rm -rf $(BROZZLER_EGG_LINK)
	rm -rf $(shell pwd)/dist

.git/hooks/pre-commit:
	ln -s $(realpath ./dev/pre-commit) $@

.PHONY: check
check:
	$(VIRTUAL_ENV_DIR)/bin/ruff check --target-version py37 .

.PHONY: check-format
check-format:
	$(VIRTUAL_ENV_DIR)/bin/ruff check --select I
	$(VIRTUAL_ENV_DIR)/bin/ruff format --check --target-version py37 .

.PHONY: format
format:
	$(VIRTUAL_ENV_DIR)/bin/ruff check --select I --fix
	$(VIRTUAL_ENV_DIR)/bin/ruff format --target-version py37 .
