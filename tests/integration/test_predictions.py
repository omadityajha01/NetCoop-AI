"""Prediction honesty (§6.2): seq ordering, no prediction on already-seen signals, tamper rejection."""

from __future__ import annotations

from netcoop.protocol.findings import Prediction
from netcoop.scoring.predictions import resolve_outcomes

SCEN = ["congestion", "interface_fault", "dns_failure", "weak_wifi", "interop"]


def test_prediction_logged_before_request_and_response(run):
    for name in SCEN:
        log = run(name).log
        msgs = log.all()
        preds = [m for m in msgs if m.message_type == "prediction"]
        assert preds, name
        for p in preds:
            pid = p.payload["prediction"]["prediction_id"]
            req = next(m for m in msgs if m.message_type == "evidence_request" and pid in m.payload["prediction_ids"])
            resp = next(m for m in msgs if m.message_type == "evidence_response" and m.in_reply_to == req.message_id)
            assert p.seq < req.seq < resp.seq, (name, pid)


def test_no_prediction_on_already_seen_signal(run):
    for name in SCEN:
        log = run(name).log
        seen: dict[str, set] = {}
        for m in log.all():
            if m.message_type in ("finding_report", "evidence_response"):
                for f in m.payload["findings"]:
                    seen.setdefault("all", set()).add((f["metric"], f["entity"]["id"]))
            if m.message_type == "prediction":
                pr = m.payload["prediction"]
                key = (pr["signal"]["metric"], pr["signal"]["entity"]["id"])
                assert key not in seen.get("all", set()), (name, key)


def test_limits_per_round(run, cfg):
    for name in SCEN:
        log = run(name).log
        by_round: dict[int, int] = {}
        for m in log.by_type("prediction"):
            r = m.payload["prediction"]["round"]
            by_round[r] = by_round.get(r, 0) + 1
        assert all(v <= cfg.agents["rounds"]["max_predictions_per_round"] for v in by_round.values())
        assert max(by_round) <= cfg.agents["rounds"]["max_rounds"]
        for m in log.by_type("evidence_request"):
            assert len(m.payload["requests"]) <= cfg.agents["rounds"]["max_evidence_requests_per_round"]


def test_every_prediction_reported(run):
    for name in SCEN:
        res = run(name)
        logged = {m.payload["prediction"]["prediction_id"] for m in res.log.by_type("prediction")}
        reported = {p["prediction_id"] for p in res.report["predictions"]}
        assert logged == reported, name
        assert all(p["outcome"] in ("hit", "miss", "unknown") for p in res.report["predictions"])


def test_tampered_prediction_after_evidence_is_rejected(run, cfg):
    """P2 is enforced in scoring: a prediction whose seq is after its evidence_response is not scored."""
    log = run("congestion").log
    msgs = [m.model_copy(deep=True) for m in log.all()]
    preds = [m for m in msgs if m.message_type == "prediction"]
    target = preds[0]
    last_seq = max(m.seq for m in msgs)
    target.seq = last_seq + 10  # pretend it was logged after looking
    out, notes = resolve_outcomes(cfg, msgs)
    p = next(x for x in out if x.prediction_id == target.payload["prediction"]["prediction_id"])
    assert isinstance(p, Prediction) and p.outcome == "unknown"
    assert any("rejected" in n for n in notes)
