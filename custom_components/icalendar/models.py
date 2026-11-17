"""Data models for iCalendar integration runtime.

The reader functions below (`calendar_selection`, `calendar_range`, `feed_name`,
`filter_settings`, `privacy_settings`, `alarm_settings`, `refresh_interval`) don't just read raw
config entry data: they also normalize it (trimming strings, coercing types,
applying defaults for missing/legacy values) so callers always get a consistent,
ready-to-use shape regardless of how the data was stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from .const import (
    CONF_ALL_DAY_ALARM_DAYS_BEFORE,
    CONF_ALL_DAY_ALARM_TIME,
    CONF_CALENDAR_ENTITY_ID,
    CONF_CALENDAR_ENTITY_IDS,
    CONF_EVENT_TYPE_FILTER,
    CONF_FEED_NAME,
    CONF_FILTER_CASE_SENSITIVE,
    CONF_FILTER_FIELDS,
    CONF_FILTER_MODE,
    CONF_FILTER_REGEX,
    CONF_FUTURE_WEEKS,
    CONF_HISTORY_WEEKS,
    CONF_PREFIX_CALENDAR_NAME,
    CONF_REFRESH_INTERVAL,
    CONF_SELECTION_MODE,
    CONF_STRIP_DESCRIPTION,
    CONF_STRIP_LOCATION,
    CONF_TIMED_ALARM_MINUTES,
    DEFAULT_ALL_DAY_ALARM_DAYS_BEFORE,
    DEFAULT_ALL_DAY_ALARM_TIME,
    DEFAULT_FILTER_FIELDS,
    DEFAULT_FUTURE_WEEKS,
    DEFAULT_HISTORY_WEEKS,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_TIMED_ALARM_MINUTES,
    EVENT_TYPE_ALL,
    FILTER_MODE_NONE,
    MODE_INCLUDE,
)


def calendar_selection(data: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Read selection, including legacy single-calendar entries."""
    entities = data.get(CONF_CALENDAR_ENTITY_IDS)
    if entities is None:
        entity = data.get(CONF_CALENDAR_ENTITY_ID)
        entities = [entity] if entity else []
    return data.get(CONF_SELECTION_MODE, MODE_INCLUDE), list(dict.fromkeys(entities))


def calendar_range(data: Mapping[str, Any]) -> tuple[int, int]:
    """Read history/future range in weeks, falling back to defaults."""
    history = data.get(CONF_HISTORY_WEEKS)
    future = data.get(CONF_FUTURE_WEEKS)
    history = DEFAULT_HISTORY_WEEKS if history is None else history
    future = DEFAULT_FUTURE_WEEKS if future is None else future
    return int(history), int(future)


def feed_name(data: Mapping[str, Any]) -> str:
    """Read the custom feed name, trimmed, defaulting to an empty string."""
    return str(data.get(CONF_FEED_NAME, "") or "").strip()


def filter_settings(
    data: Mapping[str, Any],
) -> tuple[str, str, list[str], bool, str]:
    """Read normalized event filter configuration."""
    mode = str(data.get(CONF_FILTER_MODE) or FILTER_MODE_NONE)
    regex = str(data.get(CONF_FILTER_REGEX) or "").strip()
    raw_fields = data.get(CONF_FILTER_FIELDS)
    if raw_fields is None:
        fields = list(DEFAULT_FILTER_FIELDS)
    else:
        fields = list(dict.fromkeys(str(item) for item in raw_fields))
    case_sensitive = bool(data.get(CONF_FILTER_CASE_SENSITIVE, False))
    event_type = str(data.get(CONF_EVENT_TYPE_FILTER) or EVENT_TYPE_ALL)
    return mode, regex, fields, case_sensitive, event_type


def privacy_settings(data: Mapping[str, Any]) -> tuple[bool, bool, bool]:
    """Read privacy and presentation toggles."""
    return (
        bool(data.get(CONF_STRIP_DESCRIPTION, False)),
        bool(data.get(CONF_STRIP_LOCATION, False)),
        bool(data.get(CONF_PREFIX_CALENDAR_NAME, False)),
    )


def alarm_settings(data: Mapping[str, Any]) -> tuple[int, int, str]:
    """Read default alarm settings for timed and all-day events."""
    timed = data.get(CONF_TIMED_ALARM_MINUTES)
    days_before = data.get(CONF_ALL_DAY_ALARM_DAYS_BEFORE)
    alarm_time = str(data.get(CONF_ALL_DAY_ALARM_TIME) or DEFAULT_ALL_DAY_ALARM_TIME).strip()
    return (
        DEFAULT_TIMED_ALARM_MINUTES if timed is None else int(timed),
        DEFAULT_ALL_DAY_ALARM_DAYS_BEFORE if days_before is None else int(days_before),
        alarm_time,
    )


def refresh_interval(data: Mapping[str, Any]) -> int:
    """Read feed refresh interval hint in minutes, falling back to default."""
    value = data.get(CONF_REFRESH_INTERVAL)
    return DEFAULT_REFRESH_INTERVAL if value is None else int(value)


@dataclass(slots=True)
class ICalendarRuntimeData:
    """Runtime data for one config entry."""

    calendar_entity_ids: list[str]
    selection_mode: str
    secret: str
    geocoding_url: str = ""
    history_weeks: int = DEFAULT_HISTORY_WEEKS
    future_weeks: int = DEFAULT_FUTURE_WEEKS
    feed_name: str = ""
    filter_mode: str = FILTER_MODE_NONE
    filter_regex: str = ""
    filter_fields: list[str] = field(default_factory=lambda: list(DEFAULT_FILTER_FIELDS))
    filter_case_sensitive: bool = False
    event_type_filter: str = EVENT_TYPE_ALL
    strip_description: bool = False
    strip_location: bool = False
    prefix_calendar_name: bool = False
    timed_alarm_minutes: int = DEFAULT_TIMED_ALARM_MINUTES
    all_day_alarm_days_before: int = DEFAULT_ALL_DAY_ALARM_DAYS_BEFORE
    all_day_alarm_time: str = DEFAULT_ALL_DAY_ALARM_TIME
    refresh_interval: int = DEFAULT_REFRESH_INTERVAL
    compiled_pattern: re.Pattern[str] | None = None
    cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    store: Any = None
