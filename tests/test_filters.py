"""Tests for event regex filtering, privacy stripping, and presentation transforms."""

import pytest

from custom_components.icalendar.filters import (
    compile_filter_pattern,
    filter_and_transform_events,
    validate_filter_regex,
)


def sample_events():
    return [
        {
            "start": "2026-09-10T09:00:00Z",
            "end": "2026-09-10T10:00:00Z",
            "summary": "Work Standup",
            "description": "Zoom link: https://example.com",
            "location": "Room 101",
            "_calendar_name": "Work",
        },
        {
            "start": "2026-09-11",
            "end": "2026-09-12",
            "summary": "Private: Dentist",
            "description": "Routine checkup",
            "location": "199 Clarence Street",
            "_calendar_name": "Personal",
        },
    ]


def test_validate_filter_regex():
    assert validate_filter_regex("none", "") is None
    assert validate_filter_regex("include", "") == "regex_required"
    assert validate_filter_regex("exclude", "   ") == "regex_required"
    assert validate_filter_regex("include", "[unclosed") == "invalid_regex"
    assert validate_filter_regex("include", "a" * 501) == "regex_too_long"
    assert validate_filter_regex("include", r"^(Work|Team)") is None
    assert validate_filter_regex("bad_mode", "abc") == "invalid_filter_mode"


def test_regex_include_and_exclude_case_insensitivity():
    events = sample_events()
    pattern = compile_filter_pattern("standup", case_sensitive=False)
    included = filter_and_transform_events(
        events, filter_mode="include", compiled_pattern=pattern, filter_fields=["summary"]
    )
    assert [e["summary"] for e in included] == ["Work Standup"]

    excluded = filter_and_transform_events(
        events, filter_mode="exclude", compiled_pattern=pattern, filter_fields=["summary"]
    )
    assert [e["summary"] for e in excluded] == ["Private: Dentist"]

    sensitive_pattern = compile_filter_pattern("standup", case_sensitive=True)
    assert (
        filter_and_transform_events(
            events,
            filter_mode="include",
            compiled_pattern=sensitive_pattern,
            filter_fields=["summary"],
        )
        == []
    )


def test_regex_matches_multiple_fields():
    events = sample_events()
    pattern = compile_filter_pattern("Clarence", case_sensitive=False)
    assert (
        filter_and_transform_events(
            events, filter_mode="include", compiled_pattern=pattern, filter_fields=["summary"]
        )
        == []
    )
    matched = filter_and_transform_events(
        events,
        filter_mode="include",
        compiled_pattern=pattern,
        filter_fields=["summary", "location"],
    )
    assert [e["summary"] for e in matched] == ["Private: Dentist"]


def test_event_type_filter_timed_vs_all_day():
    events = sample_events()
    timed = filter_and_transform_events(events, event_type_filter="timed")
    assert [e["summary"] for e in timed] == ["Work Standup"]

    all_day = filter_and_transform_events(events, event_type_filter="all_day")
    assert [e["summary"] for e in all_day] == ["Private: Dentist"]


def test_privacy_stripping_and_prefix_do_not_mutate_source_events():
    events = sample_events()
    transformed = filter_and_transform_events(
        events,
        strip_description=True,
        strip_location=True,
        prefix_calendar_name=True,
    )
    assert transformed[0]["summary"] == "[Work] Work Standup"
    assert "description" not in transformed[0]
    assert "location" not in transformed[0]
    # Original cached dicts remain untouched
    assert events[0]["summary"] == "Work Standup"
    assert "description" in events[0]
    assert "location" in events[0]
