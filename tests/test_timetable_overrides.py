from copy import deepcopy
from datetime import date
import sqlite3

import pytest

import app as bot
import set_up_db
import sync_schedule as ss


def block(letter, start, end):
    return {"item_type": "BLOCK", "block_code": letter,
            "start_time": start, "end_time": end}


def test_announced_special_day_restores_spare_and_corrects_stale_break():
    excursion = {"item_type": "EVENT", "block_code": None, "event_name": "Team outing",
                 "start_time": "14:00", "end_time": "16:00", "all_day": 0}
    data = {"2026-11-05": [block("E", "08:15", "09:20"), block("D", "12:05", "13:15"),
            {"item_type": "COOKIE_BREAK", "block_code": None, "start_time": "09:35", "end_time": "09:55"},
            {"item_type": "ASSEMBLY", "block_code": None, "start_time": "09:55", "end_time": "10:20"},
            excursion]}
    for _ in range(2):
        ss.complete_common_timetable(data)
        ss.apply_timetable_overrides(data)
        ss.add_fixed_timeline_items(data)
    rows = data["2026-11-05"]
    assert [(r["item_type"], r["block_code"], r["start_time"], r["end_time"]) for r in rows] == [
        ("BLOCK", "E", "08:15", "09:20"),
        ("COOKIE_BREAK", None, "09:20", "09:35"),
        ("BLOCK", "F", "09:35", "10:40"),
        ("EVENT", None, "10:45", "12:00"),
        ("BLOCK", "D", "12:05", "13:15"),
        ("EVENT", None, "14:00", "16:00"),
    ]
    assert rows[3]["event_name"] == "Remembrance Day Service"
    assert rows[-1]["event_name"] == "Team outing"


def test_override_does_not_repeat_on_other_thursdays_or_create_unrequested_dates():
    data = {"2026-11-12": [block("E", "08:15", "09:20"), block("D", "12:05", "13:15")]}
    before = deepcopy(data)
    ss.complete_common_timetable(data)
    ss.apply_timetable_overrides(data)
    ss.add_fixed_timeline_items(data)
    assert data == before  # Unknown modified day: neither F nor a break is guessed.


def test_explicit_announcement_can_fill_date_absent_from_personal_feed():
    data = {}
    ss.apply_timetable_overrides(data, include_missing=True)
    assert [r["block_code"] for r in data["2026-11-05"] if r["item_type"] == "BLOCK"] == ["E", "F", "D"]
    assert "2026-11-06" not in data


@pytest.mark.parametrize("day,observed,expected_start,expected_end", [
    ("2026-11-03", [block("D", "10:25", "11:45"), block("E", "11:55", "13:15")], "08:15", "09:35"),
    ("2026-11-05", [block("E", "08:15", "09:20"), block("D", "12:05", "13:15")], "09:35", "10:40"),
    ("2026-11-13", [block("D", "08:15", "09:35"), block("E", "10:25", "11:45")], "11:55", "13:15"),
])
def test_read_repairs_stored_personal_timetable(day, observed, expected_start, expected_end, monkeypatch):
    stored = deepcopy(observed)
    monkeypatch.setattr(bot, "query", lambda *_: deepcopy(stored))
    rows = bot.fetch_timeline_by_date(day)
    restored = [r for r in rows if r.get("block_code") == "F"]
    assert len(restored) == 1
    assert (restored[0]["start_time"], restored[0]["end_time"]) == (expected_start, expected_end)
    assert stored == observed


def test_sync_and_chat_show_special_day_without_personal_free_period(tmp_path, monkeypatch):
    path = tmp_path / "school.db"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(set_up_db, "DB_PATH", str(path))
    set_up_db.init_db()
    monkeypatch.setattr(ss, "DB_PATH", str(path))
    monkeypatch.setattr(ss, "today", lambda: date(2026, 11, 2))
    monkeypatch.setenv("MSM_ICAL_URL", "local-fixture")
    monkeypatch.setattr(ss, "fetch_ical", lambda _: """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Course-E
DTSTART;TZID=America/Vancouver:20261105T081500
DTEND;TZID=America/Vancouver:20261105T092000
END:VEVENT
BEGIN:VEVENT
SUMMARY:Course-D
DTSTART;TZID=America/Vancouver:20261105T120500
DTEND;TZID=America/Vancouver:20261105T131500
END:VEVENT
END:VCALENDAR""")
    ss.main()
    ss.main()
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT count(*) FROM ScheduleTimeline WHERE sched_date='2026-11-05'").fetchone()[0] == 5
        assert conn.execute("SELECT start_time, end_time FROM ScheduleTimeline WHERE block_code='F'").fetchone() == ("09:35", "10:40")
    monkeypatch.setattr(bot, "DB_PATH", str(path))
    monkeypatch.setattr(bot, "today", lambda: date(2026, 11, 2))
    monkeypatch.setattr(bot, "leave_on", lambda _: None)

    def no_model(*args, **kwargs):
        pytest.fail("A common block-order query should use the grounded direct answer")

    monkeypatch.setattr(bot.client.models, "generate_content", no_model)
    response = bot.app.test_client().post("/chat", json={"message": "block order Thursday"})
    assert response.status_code == 200
    reply = response.get_json()["reply"]
    assert "**Block F:** 9:35 AM – 10:40 AM" in reply
    assert "**Cookie Break:** 9:20 AM – 9:35 AM" in reply
    assert "Remembrance Day Service" in reply
    assert "spare" not in reply.lower() and "free period" not in reply.lower()
