# Thin wrapper over tasks.py (the single source of truth; Windows users run `python tasks.py <target>` directly).
PY ?= python
N ?= 280
SEED_A ?= 1000
SEED_B ?= 5000
AGENT_URL ?= http://127.0.0.1:8765
export N SEED_A SEED_B AGENT_URL

TARGETS := setup test demo eval fuzz tune sweep organizer schemas docs fixtures lint agent preflight present snapshots judge

.PHONY: $(TARGETS) conformance help
$(TARGETS):
	$(PY) tasks.py $@

conformance:
	$(PY) tasks.py conformance $(AGENT_URL)

help:
	$(PY) tasks.py help
