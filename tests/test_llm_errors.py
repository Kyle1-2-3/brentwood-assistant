import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors

import app as appmod


def _patch_llm(monkeypatch, effect):
    def fake_generate_content(**kwargs):
        if isinstance(effect, Exception):
            raise effect
        return SimpleNamespace(text=effect)
    monkeypatch.setattr(appmod.client.models, "generate_content",
                        lambda *a, **k: fake_generate_content(**k))


# ---------------------------
# classify_query
# ---------------------------
def test_classify_bad_json_logs_raw_text(monkeypatch, caplog):
    _patch_llm(monkeypatch, "sure! here are the meals you asked for")
    with caplog.at_level(logging.ERROR, logger="chatbot"), pytest.raises(appmod.ClassificationUnavailable):
        appmod.classify_query("who is the rogers houseparent")
    assert any("unparseable" in r.message and "sure!" in r.message
               for r in caplog.records)


def test_classify_api_error_logs_status(monkeypatch, caplog):
    _patch_llm(monkeypatch, errors.APIError(429, {"error": {"message": "quota exceeded"}}))
    with caplog.at_level(logging.ERROR, logger="chatbot"), pytest.raises(appmod.ClassificationUnavailable):
        appmod.classify_query("who is the rogers houseparent")
    assert any("API error" in r.message and "429" in r.message for r in caplog.records)


def test_classify_timeout_logged_as_timeout(monkeypatch, caplog):
    _patch_llm(monkeypatch, httpx.ReadTimeout("timed out"))
    with caplog.at_level(logging.ERROR, logger="chatbot"), pytest.raises(appmod.ClassificationUnavailable):
        appmod.classify_query("who is the rogers houseparent")
    assert any("timed out" in r.message for r in caplog.records)


def test_classify_unexpected_error_reports_unavailability(monkeypatch, caplog):
    _patch_llm(monkeypatch, RuntimeError("boom"))
    with caplog.at_level(logging.ERROR, logger="chatbot"), pytest.raises(appmod.ClassificationUnavailable):
        appmod.classify_query("who is the rogers houseparent")


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("failure", [
    errors.APIError(402, {"error": {"message": "private billing details"}}),
    errors.APIError(429, {"error": {"message": "quota exceeded"}}),
    errors.APIError(503, {"error": {"message": "overloaded"}}),
    httpx.ReadTimeout("timed out"),
    "invalid JSON",
    '{"requests": []}',
])
def test_classifier_failure_is_service_error_not_unknown(monkeypatch, stream, failure):
    _patch_llm(monkeypatch, failure)
    captured = []
    monkeypatch.setattr(appmod, "capture_unanswered", lambda *a, **kw: captured.append((a, kw)))

    def unexpected(*args):
        pytest.fail("A failed classifier must not look up data or ask the user to rephrase")

    monkeypatch.setattr(appmod, "build_result_from_classification", unexpected)
    monkeypatch.setattr(appmod, "unknown_reply", unexpected)
    response = appmod.app.test_client().post(
        "/chat", json={"message": "block ordee tmr"},
        headers={"Accept": "text/event-stream"} if stream else {})
    if stream:
        content = response.get_data(as_text=True)
        assert "event: error" in content
        assert "event: reply" not in content
        assert '"stage": "checking"' not in content
        payload = json.loads(content.strip().split("\n\n")[-1].split("data: ", 1)[1])
    else:
        assert response.status_code == 503
        payload = response.get_json()
    assert payload["reply"] == appmod.CLASSIFIER_FAILURE_REPLY
    assert payload["code"] == "ai_unavailable"
    assert "private billing details" not in payload["reply"]
    assert captured[0][1]["details"] == "AI classification unavailable"


def test_simple_schedule_still_works_during_ai_outage(monkeypatch):
    def unavailable(**kwargs):
        pytest.fail("A simple timetable must not call Gemini")
    monkeypatch.setattr(appmod.client.models, "generate_content", unavailable)
    response = appmod.app.test_client().post("/chat", json={"message": "block order tmr"})
    assert response.status_code == 200
    assert response.get_json()["reply"] not in appmod.UNKNOWN_REPLIES
    assert response.get_json()["reply"] != appmod.CLASSIFIER_FAILURE_REPLY


# ---------------------------
# generate_answer
# ---------------------------
def test_answer_api_error_logs_status_and_apologizes(monkeypatch, caplog):
    _patch_llm(monkeypatch, errors.APIError(503, {"error": {"message": "overloaded"}}))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        reply = appmod.generate_answer("hi", [], [])
    assert "Sorry" in reply
    assert any("API error" in r.message and "503" in r.message for r in caplog.records)


def test_answer_timeout_logged_as_timeout(monkeypatch, caplog):
    _patch_llm(monkeypatch, httpx.ReadTimeout("timed out"))
    with caplog.at_level(logging.ERROR, logger="chatbot"):
        reply = appmod.generate_answer("hi", [], [])
    assert "Sorry" in reply
    assert any("timed out" in r.message for r in caplog.records)
