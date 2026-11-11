import json

from app.api.god import _format_cursor, _parse_cursor, read_new_lines, tally_answers


def _line(**record):
    return (json.dumps(record) + "\n").encode("utf-8")


def test_reads_only_complete_lines_and_resumes_from_offset(tmp_path):
    log = tmp_path / "actions.jsonl"
    first = _line(round=1, agent_id=0, action_type="CREATE_POST")
    second = _line(round=1, agent_id=1, action_type="LIKE_POST")
    log.write_bytes(first + second[:10])  # second line still being written

    items, offset, was_reset = read_new_lines(str(log), 0, "reddit")

    assert [item["agent_id"] for item in items] == [0]
    assert items[0]["platform"] == "reddit"
    assert items[0]["seq"] == 0
    assert offset == len(first)
    assert was_reset is False

    log.write_bytes(first + second)
    items, offset, _ = read_new_lines(str(log), offset, "reddit")

    assert [item["agent_id"] for item in items] == [1]
    assert items[0]["seq"] == len(first)
    assert offset == len(first) + len(second)
    assert read_new_lines(str(log), offset, "reddit") == ([], offset, False)


def test_truncated_log_is_reported_as_reset_and_read_from_start(tmp_path):
    log = tmp_path / "actions.jsonl"
    fresh = _line(round=0, agent_id=7, action_type="CREATE_POST")
    log.write_bytes(fresh)

    items, offset, was_reset = read_new_lines(str(log), 5000, "twitter")

    assert was_reset is True
    assert [item["agent_id"] for item in items] == [7]
    assert offset == len(fresh)


def test_missing_log_resets_a_client_that_had_read_something(tmp_path):
    missing = str(tmp_path / "actions.jsonl")

    assert read_new_lines(missing, 0, "twitter") == ([], 0, False)
    assert read_new_lines(missing, 120, "twitter") == ([], 0, True)


def test_batch_limit_leaves_the_rest_for_the_next_read(tmp_path):
    log = tmp_path / "actions.jsonl"
    log.write_bytes(b"".join(_line(round=1, agent_id=i) for i in range(5)))

    items, offset, _ = read_new_lines(str(log), 0, "reddit", max_lines=2)
    rest, _, _ = read_new_lines(str(log), offset, "reddit", max_lines=10)

    assert [item["agent_id"] for item in items] == [0, 1]
    assert [item["agent_id"] for item in rest] == [2, 3, 4]


def test_malformed_and_non_utf8_lines_are_skipped(tmp_path):
    log = tmp_path / "actions.jsonl"
    good = _line(round=2, agent_id=3, action_args={"content": "学费上涨"})
    log.write_bytes(b"not json\n" + b"\xff\xfe\n" + b"[1, 2]\n" + good)

    items, offset, _ = read_new_lines(str(log), 0, "reddit")

    assert [item["agent_id"] for item in items] == [3]
    assert items[0]["action_args"]["content"] == "学费上涨"
    assert offset == log.stat().st_size


def test_cursor_round_trip_and_invalid_input():
    assert _parse_cursor("12:340:7") == {"twitter": 12, "reddit": 340, "audit": 7}
    assert _parse_cursor("12:340") == {"twitter": 12, "reddit": 340, "audit": 0}
    assert _format_cursor({"twitter": 12, "reddit": 340, "audit": 7}) == "12:340:7"
    zero = {"twitter": 0, "reddit": 0, "audit": 0}
    for bad in (None, "", "abc", "1", "1:2:3:4", "x:2"):
        assert _parse_cursor(bad) == zero
    assert _parse_cursor("-5:3") == {"twitter": 0, "reddit": 3, "audit": 0}


def test_poll_tally_matches_leading_option_and_keeps_unparsed_separate():
    answers = [
        {"agent_id": 0, "response": "Yes. It protects teaching."},
        {"agent_id": 1, "response": "**no** - we were not consulted"},
        {"agent_id": 2, "response": "Not sure, honestly."},
        {"agent_id": 3, "response": "I would rather not say"},
        {"agent_id": 4, "error": "agent missing"},
        {"agent_id": 5, "response": "Nobody asked us."},
    ]

    counts = tally_answers(answers, ["yes", "no", "not sure"])

    assert counts == {"yes": 1, "no": 1, "not sure": 1, "unparsed": 3}
    assert [a["choice"] for a in answers] == ["yes", "no", "not sure", None, None, None]
