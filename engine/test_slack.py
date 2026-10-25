"""Tests for the Slack sender (engine/slack.py). No network: the HTTP layer is stubbed.

Run: python3 engine/test_slack.py
Exit code 0 = all green.
"""

import io
import json
import os
import sys
import tempfile
import urllib.error
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from engine import audit_log  # noqa: E402
from engine import slack  # noqa: E402
from engine.alerts import pending  # noqa: E402

PASSED = []
FAILED = []


def check(name, fn):
    try:
        fn()
    except Exception as exc:
        FAILED.append((name, exc))
        print(f"FAIL {name}: {exc}")
    else:
        PASSED.append(name)
        print(f"PASS {name}")


class FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def set_env(token="test-token-123", channel="C123TEST"):
    old = {k: os.environ.get(k) for k in ("SLACK_BOT_TOKEN", "SLACK_CHANNEL", "SLACK_DRY_RUN")}
    os.environ["SLACK_BOT_TOKEN"] = token
    os.environ["SLACK_CHANNEL"] = channel
    os.environ.pop("SLACK_DRY_RUN", None)
    return old


def restore_env(old):
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_config_missing():
    old = {k: os.environ.get(k) for k in ("SLACK_BOT_TOKEN", "SLACK_CHANNEL")}
    os.environ.pop("SLACK_BOT_TOKEN", None)
    os.environ.pop("SLACK_CHANNEL", None)
    try:
        slack.config()
    except slack.NotConfigured as exc:
        assert "SLACK_BOT_TOKEN" in str(exc) and "SLACK_CHANNEL" in str(exc)
    else:
        raise AssertionError("config() should raise when env is missing")
    finally:
        restore_env(old)


def test_post_message_request():
    old = set_env()
    seen = {}
    real_urlopen = slack.urllib.request.urlopen

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        seen["body"] = json.loads(req.data)
        return FakeResponse(b'{"ok": true, "ts": "123.456"}')

    slack.urllib.request.urlopen = fake_urlopen
    try:
        resp = slack.post_message("Vendor · INV-1 · $10.00 at risk · contract_price")
    finally:
        slack.urllib.request.urlopen = real_urlopen
        restore_env(old)
    assert resp["ok"] and seen["url"] == slack.API_URL
    assert seen["auth"] == "Bearer test-token-123", seen["auth"]
    assert seen["body"] == {"channel": "C123TEST",
                            "text": "Vendor · INV-1 · $10.00 at risk · contract_price"}


def test_post_message_refused():
    old = set_env()
    real_urlopen = slack.urllib.request.urlopen
    slack.urllib.request.urlopen = lambda req, timeout=None: FakeResponse(
        b'{"ok": false, "error": "channel_not_found"}')
    try:
        slack.post_message("hi")
    except slack.SlackError as exc:
        assert "channel_not_found" in str(exc)
    else:
        raise AssertionError("refused message should raise SlackError")
    finally:
        slack.urllib.request.urlopen = real_urlopen
        restore_env(old)


def _scratch_alerts():
    tmp = Path(tempfile.mkdtemp()) / "data"
    (tmp / "results" / "discrepancy").mkdir(parents=True)
    lines = [
        {"time": "t1", "invoice": "INV-1", "text": "A · INV-1 · $10.00 at risk · contract_price", "posted": False},
        {"time": "t2", "invoice": "INV-2", "text": "B · INV-2 · needs human review · missing_evidence", "posted": False},
        {"time": "t3", "invoice": "INV-3", "text": "C · INV-3 · $5.00 at risk · duplicate", "posted": True},
    ]
    (tmp / "alerts.jsonl").write_text("".join(json.dumps(a) + "\n" for a in lines))
    return tmp


def test_post_pending_marks_only_successes():
    old = set_env()
    tmp = _scratch_alerts()
    calls = []
    real_http = slack._http_post

    def fake_http(payload, token):
        calls.append(payload["text"])
        if "INV-2" in payload["text"]:
            raise slack.SlackError("boom")
        return {"ok": True, "ts": "1"}

    slack._http_post = fake_http
    try:
        posted, failed = slack.post_pending(tmp)
    finally:
        slack._http_post = real_http
        restore_env(old)
    assert posted == [1], posted
    assert len(failed) == 1 and failed[0][0] == 2, failed
    assert [t for _, t in pending(tmp)] == ["B · INV-2 · needs human review · missing_evidence"]


def test_post_summary_text():
    old = set_env()
    tmp = Path(tempfile.mkdtemp()) / "data"
    (tmp / "results" / "discrepancy").mkdir(parents=True)
    (tmp / "results" / "success").mkdir(parents=True)
    (tmp / "results" / "discrepancy" / "INV-1.json").write_text(json.dumps(
        {"invoice": "INV-1", "status": "FAIL", "at_risk": 10.0}))
    (tmp / "results" / "success" / "INV-2.json").write_text(json.dumps(
        {"invoice": "INV-2", "status": "PASS", "at_risk": 0.0}))
    audit_log.append(tmp, "checked", "INV-1", status="FAIL")
    seen = {}
    real_http = slack._http_post

    def fake_http(payload, token):
        seen["text"] = payload["text"]
        return {"ok": True}

    slack._http_post = fake_http
    try:
        assert slack.post_summary(tmp) is True
    finally:
        slack._http_post = real_http
        restore_env(old)
    assert "audited 2 invoices" in seen["text"] and "1 failed" in seen["text"] and "$10.00 at risk" in seen["text"]


def test_dry_run_posts_nothing():
    old = set_env()
    os.environ["SLACK_DRY_RUN"] = "1"
    try:
        assert slack._http_post({"channel": "C123TEST", "text": "hi"}, "test-token-123")["ok"] is True
    finally:
        restore_env(old)


if __name__ == "__main__":
    for name, fn in [("config_missing", test_config_missing),
                     ("post_message_request", test_post_message_request),
                     ("post_message_refused", test_post_message_refused),
                     ("post_pending_marks_only_successes", test_post_pending_marks_only_successes),
                     ("post_summary_text", test_post_summary_text),
                     ("dry_run_posts_nothing", test_dry_run_posts_nothing)]:
        check(name, fn)
    print(f"\n{len(PASSED)} passed, {len(FAILED)} failed")
    sys.exit(1 if FAILED else 0)
