import json

import pytest

import app as bot


@pytest.mark.parametrize("message", [
    "How do I book the Health Centre?",
    "  HOW  DO I BOOK THE HEALTH CENTRE?!  ",
    "How can I book an appointment at the Maeda Health Center?",
])
@pytest.mark.parametrize("stream", [False, True])
def test_booking_reply_is_fixed_in_both_response_formats(monkeypatch, message, stream):
    def unexpected(*args, **kwargs):
        pytest.fail("The booking starter must not depend on the classifier or Gemini")

    monkeypatch.setattr(bot, "classify_query", unexpected)
    monkeypatch.setattr(bot.client.models, "generate_content", unexpected)
    headers = {"Accept": "text/event-stream"} if stream else {}
    response = bot.app.test_client().post("/chat", json={"message": message}, headers=headers)
    assert response.status_code == 200
    if stream:
        events = response.get_data(as_text=True).strip().split("\n\n")
        assert events[-1].startswith("event: reply\n")
        payload = json.loads(events[-1].split("data: ", 1)[1])
    else:
        payload = response.get_json()
    assert payload["reply"] == "Talk to your house parent, BFA, or teacher."
    assert payload["request_id"]


@pytest.mark.parametrize("message", [
    "Where is the Health Centre?",
    "How do I book the Health Centre and what's for lunch?",
    "How do I book the Health Centre? I have chest pain.",
])
def test_other_questions_still_reach_the_normal_pipeline(monkeypatch, message):
    seen = []

    def classify(text, memory):
        seen.append(text)
        return [{"intent": "GREETING"}]

    monkeypatch.setattr(bot, "classify_query", classify)
    monkeypatch.setattr(bot, "generate_answer", lambda *args: "Normal pipeline reply")
    response = bot.app.test_client().post("/chat", json={"message": message})
    assert seen == [message]
    assert response.get_json()["reply"] == "Normal pipeline reply"
