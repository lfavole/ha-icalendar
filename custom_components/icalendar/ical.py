"""iCalendar formatting and color resolution."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timezone
import hashlib
import json
import re
from typing import Any

from ical.calendar import Calendar
from ical.calendar_stream import IcsCalendarStream
from ical.event import Event
from ical.exceptions import CalendarParseError
from ical.parsing.property import ParsedProperty, ParsedPropertyParameter
from ical.types.geo import Geo
from homeassistant.components import frontend
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DEFAULT_ALL_DAY_ALARM_TIME
from .location import coordinates


def build_icalendar(
    hass: HomeAssistant,
    entity_id: str | None,
    calendar_name: str,
    events: list[dict[str, Any]],
    refresh_interval: int = 0,
    timed_alarm_minutes: int = -1,
    all_day_alarm_days_before: int = -1,
    all_day_alarm_time: str = DEFAULT_ALL_DAY_ALARM_TIME,
) -> str:
    """Build iCalendar feed output using HA's shared ical library."""
    calendar = Calendar()
    calendar.prodid = "-//Home Assistant//iCal Subscription 2.0//EN"
    calendar.version = "2.0"
    calendar.calscale = "GREGORIAN"

    for ha_event in events:
        if event := event_from_ha(ha_event):
            calendar.events.append(event)

    output = IcsCalendarStream.calendar_to_ics(calendar)
    return inject_calendar_metadata(
        output,
        calendar_name=calendar_name,
        calendar_color=resolve_calendar_color(hass, entity_id),
        refresh_interval=refresh_interval,
        timed_alarm_minutes=timed_alarm_minutes,
        all_day_alarm_days_before=all_day_alarm_days_before,
        all_day_alarm_time=all_day_alarm_time,
    )


def escape_text(value: str) -> str:
    """Escape an RFC 5545 TEXT value before adding content lines."""
    return (value.replace("\\", "\\\\").replace("\r\n", "\n")
            .replace("\r", "\n").replace("\n", "\\n")
            .replace(";", "\\;").replace(",", "\\,"))


def fold_line(line: str) -> str:
    """Fold at 75 UTF-8 octets without splitting a code point."""
    lines = []
    part = ""
    size = 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > 75:
            lines.append(part)
            part, size = " ", 1
        part += char
        size += width
    lines.append(part)
    return "\r\n".join(lines)


def format_ical_duration(total_minutes: int) -> str:
    """Format a signed minute offset as an RFC 5545 DURATION value."""
    if total_minutes == 0:
        return "PT0S"
    sign = "-" if total_minutes < 0 else ""
    remaining = abs(total_minutes)
    days, rem = divmod(remaining, 1440)
    hours, minutes = divmod(rem, 60)
    date_part = f"{days}D" if days else ""
    time_parts = "".join(
        part for part in (f"{hours}H" if hours else "", f"{minutes}M" if minutes else "") if part
    )
    time_part = f"T{time_parts}" if time_parts else ""
    return f"{sign}P{date_part}{time_part}"


def timed_alarm_trigger(minutes_before: int) -> str | None:
    """Return an RFC 5545 TRIGGER duration for timed events, or None when disabled."""
    if minutes_before < 0:
        return None
    return format_ical_duration(-minutes_before)


def all_day_alarm_trigger(days_before: int, alarm_time: str) -> str | None:
    """Return an RFC 5545 TRIGGER duration for all-day events, or None when disabled."""
    if days_before < 0:
        return None
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", (alarm_time or "").strip())
    if not match:
        return None
    hh, mm = int(match.group(1)), int(match.group(2))
    offset_minutes = (hh * 60 + mm) - (days_before * 1440)
    return format_ical_duration(offset_minutes)


def inject_calendar_metadata(
    ics: str,
    calendar_name: str,
    calendar_color: str | None,
    refresh_interval: int = 0,
    timed_alarm_minutes: int = -1,
    all_day_alarm_days_before: int = -1,
    all_day_alarm_time: str = DEFAULT_ALL_DAY_ALARM_TIME,
) -> str:
    """Inject calendar headers and optional default VALARM blocks."""
    # The pinned serializer folds by characters and omits DATE parameters.
    # Unfold before applying the wire-format constraints ourselves.
    unfolded = re.sub(r"\n[ \t]", "", ics.replace("\r\n", "\n"))
    lines = unfolded.split("\n")
    injected: list[str] = []
    inserted = False
    timed_trigger = timed_alarm_trigger(timed_alarm_minutes)
    all_day_trigger = all_day_alarm_trigger(all_day_alarm_days_before, all_day_alarm_time)

    in_event = False
    in_alarm = False
    is_all_day = False
    has_valarm = False
    event_summary = ""

    for line in lines:
        if not line:
            continue
        line = re.sub(r"^(DTSTART|DTEND):([0-9]{8})$",
                      r"\1;VALUE=DATE:\2", line)
        if line == "BEGIN:VEVENT":
            in_event = True
            in_alarm = False
            is_all_day = False
            has_valarm = False
            event_summary = ""
        elif in_event and line == "BEGIN:VALARM":
            in_alarm = True
            has_valarm = True
        elif in_alarm and line == "END:VALARM":
            in_alarm = False
        elif in_event and not in_alarm:
            if line.startswith("DTSTART;VALUE=DATE:"):
                is_all_day = True
            elif line.startswith("SUMMARY:"):
                event_summary = line[len("SUMMARY:"):]
        if in_event and line == "END:VEVENT":
            if not has_valarm:
                trigger = all_day_trigger if is_all_day else timed_trigger
                if trigger is not None:
                    injected.append("BEGIN:VALARM")
                    injected.append("ACTION:DISPLAY")
                    injected.append(fold_line(f"DESCRIPTION:{event_summary or 'Reminder'}"))
                    injected.append(f"TRIGGER:{trigger}")
                    injected.append("END:VALARM")
            in_event = False

        injected.append(fold_line(line))
        if not inserted and line == "VERSION:2.0":
            injected.append(fold_line(f"NAME:{escape_text(calendar_name)}"))
            injected.append(fold_line(f"X-WR-CALNAME:{escape_text(calendar_name)}"))
            if refresh_interval > 0:
                duration = f"PT{refresh_interval}M"
                injected.append(f"REFRESH-INTERVAL;VALUE=DURATION:{duration}")
                injected.append(f"X-PUBLISHED-TTL:{duration}")
            if calendar_color and is_css_color_name(calendar_color):
                injected.append(f"COLOR:{calendar_color}")
            elif calendar_color and is_hex_color(calendar_color):
                injected.append(f"X-APPLE-CALENDAR-COLOR:{calendar_color}")
            inserted = True
    return "\r\n".join(injected) + "\r\n"


def event_from_ha(event: dict[str, Any]) -> Event | None:
    """Convert Home Assistant event payload to an ical.Event."""
    try:
        start = parse_ha_datetime_or_date(event["start"])
        end = parse_ha_datetime_or_date(event["end"])
        if type(start) is not type(end) or end <= start:
            return None
        # HA returns expanded occurrences, not recurrence rules. Include the
        # occurrence start so repeated instances with the same source UID differ.
        identity = [event.get("_calendar_entity_id", ""),
                    str(event.get("uid") or event.get("summary") or ""),
                    start.isoformat()]
        uid = hashlib.sha256(json.dumps(identity).encode("utf-8")).hexdigest()
        result = Event(
            uid=f"{uid}@ha-icalendar",
            summary=str(event.get("summary") or ""),
            start=start,
            end=end,
            description=event.get("description"),
            location=event.get("location"),
        )
        if result.location and (point := coordinates(event.get("_location_coordinates"))):
            result.geo = Geo(*point)
            title = result.location.replace("\r\n", "\n").replace("\r", "\n")
            result.extras.append(ParsedProperty(
                name="X-APPLE-STRUCTURED-LOCATION",
                value=f"geo:{point[0]},{point[1]}",
                params=[
                    ParsedPropertyParameter(name="VALUE", values=["URI"]),
                    ParsedPropertyParameter(name="X-ADDRESS", values=[title]),
                    ParsedPropertyParameter(name="X-APPLE-RADIUS", values=["100"]),
                    ParsedPropertyParameter(name="X-TITLE", values=[title]),
                ],
            ))
        return result
    except (KeyError, ValueError, TypeError, CalendarParseError):
        return None


def parse_ha_datetime_or_date(value: str) -> datetime | date:
    """Parse HA event date/datetime string."""
    if "T" in value:
        parsed = datetime.fromisoformat(value)
        # Numeric offsets otherwise become undefined TZIDs in the ICS library.
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed
    return datetime.strptime(value, "%Y-%m-%d").date()


def resolve_calendar_color(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Resolve calendar color from HA entity options."""
    resolved: str | None = None
    if entity_id is None:
        return None
    registry = er.async_get(hass)
    if registry_entry := registry.async_get(entity_id):
        if color := registry_entry.options.get("calendar", {}).get("color"):
            resolved = str(color)
    return normalize_calendar_color(hass, resolved)


def normalize_calendar_color(hass: HomeAssistant, color: str | None) -> str | None:
    """Normalize calendar color token into a concrete ICS-friendly color."""
    if not color:
        return None

    value = color.strip()
    if not value:
        return None

    if is_hex_color(value) or is_css_color_name(value):
        return value

    lowered = value.lower()
    theme_vars = active_theme_vars(hass)
    semantic_map = {
        "primary": "primary-color",
        "accent": "accent-color",
    }
    if (theme_key := semantic_map.get(lowered)) and (theme_value := theme_vars.get(theme_key)):
        theme_color = str(theme_value).strip()
        if is_hex_color(theme_color) or is_css_color_name(theme_color):
            return theme_color

    if lowered == "primary":
        return frontend.DEFAULT_THEME_COLOR

    return None


def active_theme_vars(hass: HomeAssistant) -> Mapping[str, Any]:
    """Return active frontend theme variables if available."""
    themes = hass.data.get(frontend.DATA_THEMES, {})
    if not isinstance(themes, dict):
        return {}

    active_theme = hass.data.get(frontend.DATA_DEFAULT_THEME, frontend.DEFAULT_THEME)
    if not active_theme or active_theme == frontend.DEFAULT_THEME:
        return {}

    variables = themes.get(active_theme, {})
    if isinstance(variables, dict):
        return variables
    return {}


def is_hex_color(value: str) -> bool:
    """Check whether value is a #RGB or #RRGGBB hex color."""
    return bool(re.fullmatch(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?", value))


def is_css_color_name(value: str) -> bool:
    """Check the named colors allowed by RFC 7986."""
    return value.lower() in CSS3_COLOR_NAMES


# CSS Color Module Level 3, section 4.3 (RFC 7986 COLOR values).
CSS3_COLOR_NAMES = frozenset(
    'aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue '
    'blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk '
    'crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki '
    'darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen '
    'darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue '
    'dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro '
    'ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo '
    'ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan '
    'lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen '
    'lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen '
    'linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple '
    'mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred '
    'midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab '
    'orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip '
    'peachpuff peru pink plum powderblue purple red rosybrown royalblue saddlebrown salmon '
    'sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow '
    'springgreen steelblue tan teal thistle tomato turquoise violet wheat white whitesmoke '
    'yellow yellowgreen '
    .split()
)
