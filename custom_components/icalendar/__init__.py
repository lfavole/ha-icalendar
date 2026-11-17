"""iCalendar integration setup and entry lifecycle."""

from __future__ import annotations

import logging
import re

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .const import CONF_SECRET, DOMAIN
from .filters import compile_filter_pattern
from .http import ICalendarView
from .location import CONF_GEOCODING_URL, LocationResolver
from .models import (
    ICalendarRuntimeData,
    alarm_settings,
    calendar_range,
    calendar_selection,
    feed_name,
    filter_settings,
    privacy_settings,
    refresh_interval,
)

_LOGGER = logging.getLogger(__name__)
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the iCalendar component."""
    hass.data.setdefault(DOMAIN, {})
    if not hass.data[DOMAIN].get("view_registered"):
        resolver = LocationResolver(hass)
        await resolver.async_load()
        hass.http.register_view(ICalendarView(hass, resolver))
        hass.data[DOMAIN]["view_registered"] = True
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up iCalendar from a config entry."""
    mode, entity_ids = calendar_selection(entry.data)
    history_weeks, future_weeks = calendar_range(entry.data)
    filter_mode, filter_regex, filter_fields, case_sensitive, event_type = filter_settings(
        entry.data
    )
    strip_description, strip_location, prefix_calendar_name = privacy_settings(entry.data)
    timed_alarm, all_day_days, all_day_time = alarm_settings(entry.data)
    interval = refresh_interval(entry.data)

    compiled_pattern = None
    if filter_regex:
        try:
            compiled_pattern = compile_filter_pattern(filter_regex, case_sensitive)
        except re.error:
            _LOGGER.warning(
                "Invalid filter_regex configured on entry %s; regex filter disabled",
                entry.entry_id,
            )

    store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.events")
    cached = await store.async_load()
    entry.runtime_data = ICalendarRuntimeData(
        calendar_entity_ids=entity_ids,
        selection_mode=mode,
        secret=entry.data[CONF_SECRET],
        geocoding_url=entry.data.get(CONF_GEOCODING_URL, ""),
        history_weeks=history_weeks,
        future_weeks=future_weeks,
        feed_name=feed_name(entry.data),
        filter_mode=filter_mode,
        filter_regex=filter_regex,
        filter_fields=filter_fields,
        filter_case_sensitive=case_sensitive,
        event_type_filter=event_type,
        strip_description=strip_description,
        strip_location=strip_location,
        prefix_calendar_name=prefix_calendar_name,
        timed_alarm_minutes=timed_alarm,
        all_day_alarm_days_before=all_day_days,
        all_day_alarm_time=all_day_time,
        refresh_interval=interval,
        compiled_pattern=compiled_pattern,
        cache=cached or {},
        store=store,
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an iCalendar config entry and revoke access to its feed."""
    entry.runtime_data = None
    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove stored calendar data when deleting an entry."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.events").async_remove()
