"""Diagnostics support for iCalendar integration."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import CONF_SECRET, MODE_EXCLUDE
from .models import (
    calendar_selection,
    filter_settings,
    privacy_settings,
    refresh_interval,
)

TO_REDACT = {CONF_SECRET}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict:
    """Return diagnostics for a config entry."""
    registry = er.async_get(hass)
    mode, entity_ids = calendar_selection(entry.data)
    resolved_ids = entity_ids
    if mode == MODE_EXCLUDE:
        excluded = set(entity_ids)
        resolved_ids = sorted(
            entity_id
            for entity_id in hass.states.async_entity_ids("calendar")
            if entity_id not in excluded
        )

    entities = {}
    for entity_id in resolved_ids:
        registry_entry = registry.async_get(entity_id)
        entities[entity_id] = {
            "entity_exists": hass.states.get(entity_id) is not None,
            "disabled_by": registry_entry.disabled_by if registry_entry else None,
            "has_calendar_color": bool(
                registry_entry and registry_entry.options.get("calendar", {}).get("color")
            ),
        }

    filter_mode, filter_regex, filter_fields, case_sensitive, event_type = filter_settings(
        entry.data
    )
    strip_description, strip_location, prefix_calendar_name = privacy_settings(entry.data)
    runtime_data = getattr(entry, "runtime_data", None)
    cache_summary = (
        {
            entity_id: len(payload.get("events", []))
            for entity_id, payload in runtime_data.cache.items()
        }
        if runtime_data is not None
        else {}
    )

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "selection_mode": mode,
        "entities": entities,
        "filter": {
            "mode": filter_mode,
            "regex": filter_regex,
            "fields": filter_fields,
            "case_sensitive": case_sensitive,
            "event_type": event_type,
        },
        "privacy": {
            "strip_description": strip_description,
            "strip_location": strip_location,
            "prefix_calendar_name": prefix_calendar_name,
        },
        "refresh_interval_minutes": refresh_interval(entry.data),
        "cached_event_counts": cache_summary,
    }
