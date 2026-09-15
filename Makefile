PYTHON ?= python3
PY = .venv/bin/python
COMPOSE ?= docker compose
export MPLCONFIGDIR := $(CURDIR)/.mplconfig
.NOTPARALLEL:
.PHONY: up down load bench stale chart readme all clean test

.venv/.installed: requirements.txt
	$(PYTHON) -m venv .venv
	$(PY) -m pip install -r requirements.txt
	touch $@

up:
	$(COMPOSE) up -d --wait

down:
	$(COMPOSE) down

load: .venv/.installed
	$(PY) -m qpl.generate

bench: .venv/.installed
	$(PY) -m qpl.runner

stale: .venv/.installed
	$(PY) -m qpl.stale_stats --cleanup

chart: .venv/.installed
	$(PY) -m qpl.plot

readme: .venv/.installed
	$(PY) -m qpl.report

all: up load bench stale chart readme
	$(PY) -m qpl.validate

test: .venv/.installed
	$(PY) -m unittest discover -s tests -v

clean:
	$(COMPOSE) down --volumes
	$(PYTHON) -c "from pathlib import Path; [p.unlink() for p in Path('results').rglob('*') if p.is_file() and p.name != '.gitkeep']"
