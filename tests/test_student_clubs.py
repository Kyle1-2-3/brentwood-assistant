"""Exercise club retrieval and the evidence sent to the answer model."""
import json
from types import SimpleNamespace

import pytest

import app as bot
import school_knowledge as kb


@pytest.mark.parametrize("query,expected", [
    ("Tell me about clubs", "student-club-info-2026-27"),
    ("What clubs can I join?", "student-club-info-2026-27"),
    ("SAC meeting time and location", "club-sac-2026-27"),
    ("BWell", "club-bwell-2026-27"),
    ("B-Well meeting", "club-bwell-2026-27"),
    ("B Well contacts", "club-bwell-2026-27"),
    ("BIPOC meeting time location captain", "club-bipoc-2026-27"),
    ("women society", "club-womens-society-2026-27"),
    ("Women's Society meeting", "club-womens-society-2026-27"),
    ("Women’s Society meeting", "club-womens-society-2026-27"),
    ("Womens Society captains", "club-womens-society-2026-27"),
    ("BEAT meeting time", "club-beat-2026-27"),
    ("OMNI meeting", "club-omni-2026-27"),
])
def test_current_club_profile_precedes_older_mentions(query, expected):
    assert kb.search_school_knowledge(query, limit=1)[0]["id"] == expected


def test_multiple_requested_clubs_and_review_dates():
    results = kb.search_school_knowledge("BIPOC and OMNI meeting", limit=2)
    assert {r["id"] for r in results} == {"club-bipoc-2026-27", "club-omni-2026-27"}
    assert all(r["checked_on"] == "2026-11-02" for r in results)
    public = next(r for r in kb.search_school_knowledge("Rogers houseparent")
                  if r.get("source_type") != "curated_club_email")
    assert public["checked_on"] == "2026-09-23"


def test_reviewed_schedules_keep_latest_notices_and_dated_exception():
    sac = kb.search_school_knowledge("SAC meeting", limit=1)[0]
    women = kb.search_school_knowledge("Women's Society", limit=1)[0]
    bwell = kb.search_school_knowledge("BWell", limit=1)[0]
    omni = kb.search_school_knowledge("OMNI", limit=1)[0]
    assert any("every Tuesday" in f and "cookie break" in f for f in sac["facts"])
    assert any("October 27, 2026" in f and "cancelled" in f for f in sac["facts"])
    assert any("every Monday" in f and "1:20 PM to 1:50 PM" in f for f in women["facts"])
    assert any("every Friday at 6:30 PM in McNeill's" in f for f in bwell["facts"])
    assert any("every Tuesday at 6:00 PM" in f for f in omni["facts"])
    for record in (sac, women, bwell):
        assert any(s["kind"] == "project_owner_confirmation" for s in record["sources"])


def test_curated_records_have_citations_without_private_mail_data():
    records = [r for r in kb.load_knowledge()["records"]
               if r.get("source_type") == "curated_club_email"]
    assert len(records) == 7  # Six profiles and the overview.
    for record in records:
        assert record["source_label"] and record["sources"]
        assert record["academic_year"] == "2026/27"
        assert not record.get("source_url")
    serialized = json.dumps(records)
    for private in ("mail.google.com", "@brentwood.ca", "message_id", "thread_id",
                    "authuser", "classroom code", "docs.google.com/forms"):
        assert private not in serialized.lower()


def test_answer_payload_keeps_mixed_review_dates():
    records = kb.search_school_knowledge("BWell")
    result = bot.focused_answer_results([{"intent": "SCHOOL_INFO"}],
                                       [{"type": "SCHOOL_INFO", "records": records}])[0]
    assert "checked_on" not in result
    assert result["records"][0]["checked_on"] == "2026-11-02"
    assert any(r["checked_on"] == "2026-09-23" for r in result["records"])


@pytest.mark.parametrize("content", [None, "{broken", '{"records": {}}'])
def test_unavailable_club_snapshot_preserves_public_knowledge(tmp_path, monkeypatch, content):
    path = tmp_path / "clubs.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setattr(kb, "CLUB_KNOWLEDGE_PATH", path)
    kb.load_knowledge.cache_clear()
    try:
        assert kb.search_school_knowledge("Rogers houseparent")
        assert not any(r.get("source_type") == "curated_club_email"
                       for r in kb.load_knowledge()["records"])
    finally:
        kb.load_knowledge.cache_clear()


def test_chat_passes_current_club_facts_without_citations(monkeypatch):
    monkeypatch.setenv("FAKE_TODAY", "2026-11-02")
    monkeypatch.setattr(bot, "classify_query", lambda *args: [
        {"intent": "SCHOOL_INFO", "school_query": "BIPOC meeting captain"}])
    captured = {}

    def generate(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="BIPOC meets Thursdays at 6:15 PM in A255.")

    monkeypatch.setattr(bot.client.models, "generate_content", generate)
    response = bot.app.test_client().post("/chat", json={"message": "When is BIPOC?"})
    assert response.status_code == 200
    records = json.loads(captured["contents"])["results"][0]["records"]
    assert records[0]["title"] == "BIPOC club (2026/27)"
    assert any("Joanna Fakulujo" in f and "Ms. Gage" in f for f in records[0]["facts"])
    assert records[0]["source_type"] == "curated_club_email"
    assert "sources" not in records[0] and "source_label" not in records[0]
    prompt = captured["config"].system_instruction
    assert "Do not include source citations" in prompt
    assert "cancellation applies only to that date" in prompt
    assert "mail.google.com" not in captured["contents"]


def test_source_links_are_removed_without_losing_facts_or_action_links():
    original = {
        "type": "SCHOOL_BREAKS", "source_url": "https://example.com/calendar",
        "source_title": "School calendar",
        "leaves": [{"start_date": "2026-12-18", "return_date": "2027-01-05",
                    "travel_source_url": "https://example.com/travel"}],
        "source_conflict": {"url": "https://example.com/a", "other_url": "https://example.com/b",
                            "detail": "Current role unconfirmed."},
        "myschool_url": "https://example.com/myschool",
        "menu_items": [{"name": "Ravioli", "search_url": "https://example.com/images"}],
    }
    result = bot.focused_answer_results([], [original])[0]
    assert "source_url" not in result and "source_title" not in result
    assert result["leaves"] == [{"start_date": "2026-12-18", "return_date": "2027-01-05"}]
    assert result["source_conflict"] == {"detail": "Current role unconfirmed."}
    assert result["myschool_url"] == original["myschool_url"]
    assert result["menu_items"] == original["menu_items"]
    assert original["source_url"]  # Stored/internal records are not mutated.
