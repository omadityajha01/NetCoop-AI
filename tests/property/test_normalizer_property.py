"""Property tests: the normalizer never crashes; output is always valid or a structured error."""

from __future__ import annotations

import json

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from netcoop.normalize.pipeline import NormalizationError, normalize_bundle
from netcoop.protocol.versions import parse_message

FIELDS = ["latency_ms", "latency", "rtt", "cpu_utilization_pct", "cpu", "utilization", "queue_drops", "mem",
          "packet_loss_pct", "rssi", "signal", "dns_failure_pct", "zzz", "status", "units", "metric", "value"]
IDS = ["SW_CAMPUS_1", "sw-campus-2", "10.40.0.3", "AP_H3", "ap-h1", "DNS_01", "L_DC_UPLINK", "ghost", "", "x" * 80, "a b"]
KEYS = ["device_id", "ap", "link_id", "service", "entity", "host", "nothing"]
scalars = st.one_of(st.none(), st.booleans(), st.integers(-10**9, 10**9), st.floats(allow_nan=True, allow_infinity=True),
                    st.text(max_size=12), st.sampled_from(["N/A", "12ms", "0.3s", "45 %", "1e3", "-", "15 pkts"]))
times = st.one_of(st.sampled_from(["2026-10-31T10:00:00Z", "2026-10-31T09:45:00+05:30", "2026-10-31 09:50:00", "garbage", ""]),
                  st.integers(0, 2_000_000_000), st.none())
record = st.fixed_dictionaries(
    {"timestamp": times},
    optional={k: st.one_of(st.sampled_from(IDS), scalars) for k in KEYS}
    | {"metrics": st.dictionaries(st.sampled_from(FIELDS), scalars, max_size=6),
       "units": st.dictionaries(st.sampled_from(FIELDS), st.sampled_from(["ms", "s", "pct", "fraction", "furlong", ""]), max_size=3),
       "source": st.text(max_size=10)})
anything = st.recursive(scalars, lambda c: st.lists(c, max_size=4) | st.dictionaries(st.text(max_size=6), c, max_size=4),
                        max_leaves=20)
bundles = st.one_of(
    st.fixed_dictionaries({"records": st.lists(st.one_of(record, anything), max_size=15)},
                          optional={"schema_version": st.sampled_from(["1.0", "1.3", "0.9", "2.0", 7]),
                                    "incident": st.fixed_dictionaries({}, optional={"time": times, "complaint": st.text(max_size=50)})}),
    st.lists(record, max_size=10), anything)


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(bundles)
def test_normalizer_never_crashes(cfg, data):
    try:
        res = normalize_bundle(json.dumps(data, default=str).encode(), cfg)
    except NormalizationError as e:
        assert e.code in ("MALFORMED", "MISSING_FIELD", "BAD_TYPE", "SCHEMA_VERSION_UNSUPPORTED", "TOO_LARGE")
        return
    assert res.records_in == res.records_used + res.records_quarantined
    for o in res.observations:
        spec = cfg.metrics[o.metric]
        lo, hi = spec["range"]
        assert lo <= o.value <= hi
        assert o.unit == spec["unit"]
        assert cfg.topology.exists(o.entity_id)


@settings(max_examples=200, deadline=None)
@given(st.binary(max_size=300))
def test_normalizer_random_bytes(cfg, raw):
    try:
        normalize_bundle(raw, cfg)
    except NormalizationError:
        pass


@settings(max_examples=250, deadline=None)
@given(anything)
def test_parse_message_never_raises(raw):
    pr = parse_message(raw)
    assert (pr.message is None) != (pr.error_code is None)
