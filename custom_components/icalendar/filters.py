"""Event filtering and transformation helpers for iCalendar feeds."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

from .const import (
    DEFAULT_FILTER_FIELDS,
    EVENT_TYPE_ALL,
    EVENT_TYPE_ALL_DAY,
    EVENT_TYPE_TIMED,
    FILTER_MODE_EXCLUDE,
    FILTER_MODE_INCLUDE,
    FILTER_MODE_NONE,
    MAX_FILTER_REGEX_LENGTH,
    VALID_EVENT_TYPES,
    VALID_FILTER_FIELDS,
    VALID_FILTER_MODES,
)


def compile_filter_pattern(
    pattern: str, case_sensitive: bool = False
) -> re.Pattern[str] | None:
    """Compile a regex pattern if non-empty, returning None if blank."""
    cleaned = (pattern or "").strip()
    if not cleaned:
        return None
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(cleaned, flags)


def validate_filter_regex(mode: str, pattern: str) -> str | None:
    """Return a translation error key if the regex configuration is invalid."""
    if mode not in VALID_FILTER_MODES:
        return "invalid_filter_mode"
    cleaned = (pattern or "").strip()
    if mode == FILTER_MODE_NONE:
        if not cleaned:
            return None
        if len(cleaned) > MAX_FILTER_REGEX_LENGTH:
            return "regex_too_long"
        try:
            re.compile(cleaned)
        except re.error:
            return "invalid_regex"
        return None
    if not cleaned:
        return "regex_required"
    if len(cleaned) > MAX_FILTER_REGEX_LENGTH:
        return "regex_too_long"
    try:
        re.compile(cleaned)
    except re.error:
        return "invalid_regex"
    return None


def is_all_day_event(event: Mapping[str, Any]) -> bool:
    """Return True if an HA event dict represents an all-day DATE event."""
    start = event.get("start")
    return isinstance(start, str) and "T" not in start


def matches_event_type(event: Mapping[str, Any], event_type_filter: str) -> bool:
    """Check whether an event satisfies the timed/all-day filter."""
    if event_type_filter == EVENT_TYPE_ALL:
        return True
    all_day = is_all_day_event(event)
    if event_type_filter == EVENT_TYPE_ALL_DAY:
        return all_day
    if event_type_filter == EVENT_TYPE_TIMED:
        return not all_day
    return True


def matches_regex(
    event: Mapping[str, Any],
    pattern: re.Pattern[str],
    fields: Sequence[str],
) -> bool:
    """Return True if any selected event field matches the compiled regex."""
    for field_name in fields:
        value = event.get(field_name)
        if value is not None and pattern.search(str(value)):
            return True
    return False


def filter_and_transform_events(
    events: Sequence[Mapping[str, Any]],
    *,
    filter_mode: str = FILTER_MODE_NONE,
    compiled_pattern: re.Pattern[str] | None = None,
    filter_fields: Sequence[str] = DEFAULT_FILTER_FIELDS,
    event_type_filter: str = EVENT_TYPE_ALL,
    strip_description: bool = False,
    strip_location: bool = False,
    prefix_calendar_name: bool = False,
) -> list[dict[str, Any]]:
    """Filter events and apply non-destructive presentation/privacy transforms."""
    active_fields = [f for f in filter_fields if f in VALID_FILTER_FIELDS] or list(
        DEFAULT_FILTER_FIELDS
    )
    normalized_type = (
        event_type_filter if event_type_filter in VALID_EVENT_TYPES else EVENT_TYPE_ALL
    )

    result: list[dict[str, Any]] = []
    for raw_event in events:
        if not matches_event_type(raw_event, normalized_type):
            continue

        if compiled_pattern is not None and filter_mode in (
            FILTER_MODE_INCLUDE,
            FILTER_MODE_EXCLUDE,
        ):
            matched = matches_regex(raw_event, compiled_pattern, active_fields)
            if filter_mode == FILTER_MODE_INCLUDE and not matched:
                continue
            if filter_mode == FILTER_MODE_EXCLUDE and matched:
                continue

        event = dict(raw_event)
        if prefix_calendar_name:
            cal_name = str(event.get("_calendar_name") or "").strip()
            if cal_name:
                summary = str(event.get("summary") or "").strip()
                event["summary"] = f"[{cal_name}] {summary}" if summary else f"[{cal_name}]"

        if strip_description:
            event.pop("description", None)
        if strip_location:
            event.pop("location", None)

        result.append(event)

    return result
