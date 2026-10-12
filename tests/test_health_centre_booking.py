import json
from types import SimpleNamespace

import pytest

import app as bot
from answer_prompts import ANSWER_RULES


@pytest.mark.parametrize("message", [
    "How do I book the Health Centre?",
    "  HOW  DO I BOOK THE HEALTH CENTRE?!  ",
    "How can I book an appointment at the Maeda Health Center?",
])
@pytest.mark.parametrize("stream", [False, True])
def test_booking_generates_varied_wording_from_the_same_contacts(monkeypatch, message, stream):
    variants = [
        "To book a Health Centre appointment, speak with your house parent, a BFA, or a teacher.",
        "Your house parent, a BFA, or a teacher is someone you can talk to about booking the Health Centre.",
    ]
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text=variants[len(calls) - 1])

    monkeypatch.setattr(bot.client.models, "generate_content", generate)
    headers = {"Accept": "text/event-stream"} if stream else {}
    memory = ""
    for variant in variants:
        response = bot.app.test_client().post("/chat", json={"message": message, "memory": memory}, headers=headers)
        assert response.status_code == 200
        if stream:
            events = response.get_data(as_text=True).strip().split("\n\n")
            assert events[-1].startswith("event: reply\n")
            payload = json.loads(events[-1].split("data: ", 1)[1])
        else:
            payload = response.get_json()
        assert payload["reply"] == variant
        assert payload["request_id"]
        memory = f"Student: {message}\nAssistant: {variant}"
    assert len(calls) == 2  # One answer call per request; no classification call.
    for call in calls:
        data = json.loads(call["contents"])
        assert data["user_message"] == message.strip()
        assert data["results"][0]["contacts"] == ["house parent", "BFA", "teacher"]
        assert ANSWER_RULES["HEALTH_CENTRE_BOOKING"].strip() in call["config"].system_instruction
    assert variants[0] in json.loads(calls[1]["contents"])["recent_conversation"]


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


def test_paraphrased_booking_and_another_question_keep_both_answers(monkeypatch):
    calls = []
    requests = [{"intent": "HEALTH_CENTRE_BOOKING"}, {"intent": "LOCATION"}]

    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(text=json.dumps({"requests": requests}))
        return SimpleNamespace(text="Speak with your house parent, a BFA, or a teacher about booking. Use the campus map to find it.")

    monkeypatch.setattr(bot.client.models, "generate_content", generate)
    response = bot.app.test_client().post("/chat", json={
        "message": "Who can help arrange a nurse appointment, and where is the Health Centre?"})
    assert response.status_code == 200
    assert len(calls) == 2
    results = json.loads(calls[-1]["contents"])["results"]
    assert [result["type"] for result in results] == ["HEALTH_CENTRE_BOOKING", "LOCATION"]
    assert results[0]["contacts"] == ["house parent", "BFA", "teacher"]
    assert "campus map" in response.get_json()["reply"]
