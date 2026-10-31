PY ?= python
N ?= 280
SEED_A ?= 1000
SEED_B ?= 5000
AGENT_URL ?= http://127.0.0.1:8765

.PHONY: setup test demo eval fuzz tune conformance schemas docs fixtures lint agent

setup:
	$(PY) -m pip install -e .[dev]

test:
	$(PY) -m pytest tests -q -p no:warnings

demo:
	$(PY) -m netcoop demo

eval:
	$(PY) -m eval.run_eval eval --n $(N) --seed-a $(SEED_A) --seed-b $(SEED_B)

fuzz:
	$(PY) -m eval.run_eval fuzz --n 70

tune:
	$(PY) -m eval.run_eval tune --n $(N) --seed-a $(SEED_A)

conformance:
	$(PY) -m conformance.kit $(AGENT_URL)

schemas:
	$(PY) -m netcoop schemas

docs:
	$(PY) -m netcoop docs

fixtures:
	$(PY) -m eval.generate --fixtures

lint:
	$(PY) -m ruff check netcoop eval conformance tests tasks.py

agent:
	node external_agents/wireless_agent/server.js
