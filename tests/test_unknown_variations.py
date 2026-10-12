import json

import pytest

import app as bot


@pytest.mark.parametrize("stream", [False, True])
def test_unknown_replies_vary_and_capture_the_displayed_answer(monkeypatch, stream):
    monkeypatch.setattr(bot, "classify_query", lambda *args: [dict(bot.UNKNOWN_REQUEST)])
    # Make selection deterministic to prove that memory, not luck, prevents repeats.
    monkeypatch.setattr(bot.random, "choice", lambda options: options[0])
    captured = []
    monkeypatch.setattr(bot, "capture_unanswered", lambda *args: captured.append(args))

    def unexpected(*args, **kwargs):
        pytest.fail("An UNKNOWN fallback must not make another model call")

    monkeypatch.setattr(bot.client.models, "generate_content", unexpected)
    client = bot.app.test_client()
    headers = {"Accept": "text/event-stream"} if stream else {}
    memory, seen = "", []
    for index in range(len(bot.UNKNOWN_REPLIES) + 1):
        response = client.post("/chat", json={"message": "asdf", "memory": memory}, headers=headers)
        assert response.status_code == 200
        if stream:
            events = response.get_data(as_text=True).strip().split("\n\n")
            assert events[-1].startswith("event: reply\n")
            payload = json.loads(events[-1].split("data: ", 1)[1])
        else:
            payload = response.get_json()
        reply = payload["reply"]
        assert reply in bot.UNKNOWN_REPLIES
        if index < len(bot.UNKNOWN_REPLIES):
            assert reply not in seen
        else:
            assert reply == seen[0] and reply != seen[-1]
        assert captured[-1] == (payload["request_id"], "asdf", reply)
        seen.append(reply)
        # Exercise punctuation/case normalization as well as normal chat history.
        memory += f"\nStudent: asdf\nAssistant: **{reply.upper()}**"
