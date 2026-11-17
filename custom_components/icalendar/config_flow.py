"""Config flow for iCalendar API."""

from __future__ import annotations

from collections.abc import Mapping
import re
import secrets
from typing import Any
from urllib.parse import quote

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import SOURCE_USER, FlowType
from homeassistant.core import HomeAssistant
from homeassistant.helpers import selector

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
    CONF_SECRET,
    CONF_SELECTION_MODE,
    CONF_STRIP_DESCRIPTION,
    CONF_STRIP_LOCATION,
    CONF_TIMED_ALARM_MINUTES,
    DOMAIN,
    FILTER_MODE_NONE,
    MAX_ALARM_MINUTES,
    MAX_ALL_DAY_ALARM_DAYS_BEFORE,
    MAX_FEED_NAME_LENGTH,
    MAX_FUTURE_WEEKS,
    MAX_HISTORY_WEEKS,
    MAX_REFRESH_INTERVAL,
    MODE_EXCLUDE,
    MODE_INCLUDE,
    NAME,
    URL_PATH_PREFIX,
    VALID_EVENT_TYPES,
    VALID_FILTER_FIELDS,
    VALID_FILTER_MODES,
)
from .filters import validate_filter_regex
from .location import CONF_GEOCODING_URL, is_valid_geocoding_url
from .models import (
    alarm_settings,
    calendar_range,
    calendar_selection,
    feed_name,
    filter_settings,
    privacy_settings,
    refresh_interval,
)


def _generate_secret() -> str:
    """Generate a URL-safe secret."""
    return secrets.token_urlsafe(24)


def _is_secret_valid(secret: str) -> bool:
    """Validate secret length/strength for URL auth."""
    return bool(re.fullmatch(r"[A-Za-z0-9_-]{20,}", secret))


def _build_feed_urls(hass: HomeAssistant, entry_id: str, secret: str) -> tuple[str, str]:
    """Build local/internal and external URLs where available."""
    path = f"{URL_PATH_PREFIX}/{entry_id}/{quote(secret, safe='')}.ics"

    local_base = hass.config.internal_url or ""
    external_base = hass.config.external_url or ""

    local_url = f"{local_base.rstrip('/')}{path}" if local_base else ""
    external_url = f"{external_base.rstrip('/')}{path}" if external_base else ""

    return local_url, external_url


def _build_urls_text(local_url: str, external_url: str) -> str:
    """Create URL description block with only available URLs."""
    lines: list[str] = []
    if local_url:
        lines.append(f"Current local URL:\n{local_url}")
    if external_url:
        lines.append(f"Current external URL:\n{external_url}")
    return "\n".join(lines)


def _title_for_selection(mode: str, entity_ids: list[str], custom_name: str = "") -> str:
    """Build a title describing the feed selection."""
    if custom_name:
        return custom_name
    return f"{NAME} ({mode}: {', '.join(entity_ids) or 'none'})"


def _selection_errors(hass: HomeAssistant, data: Mapping[str, Any]) -> dict[str, str]:
    if not is_valid_geocoding_url(data.get(CONF_GEOCODING_URL, "")):
        return {CONF_GEOCODING_URL: "invalid_geocoding_url"}
    mode, entities = calendar_selection(data)
    if mode not in (MODE_INCLUDE, MODE_EXCLUDE):
        return {CONF_SELECTION_MODE: "invalid_selection_mode"}
    if mode == MODE_INCLUDE and not entities:
        return {CONF_CALENDAR_ENTITY_IDS: "no_calendars"}
    if any(not entity.startswith("calendar.") or hass.states.get(entity) is None
           for entity in entities):
        return {CONF_CALENDAR_ENTITY_IDS: "entity_not_found"}
    try:
        history_weeks, future_weeks = calendar_range(data)
    except (TypeError, ValueError):
        return {CONF_HISTORY_WEEKS: "invalid_range"}
    if not (0 <= history_weeks <= MAX_HISTORY_WEEKS):
        return {CONF_HISTORY_WEEKS: "invalid_range"}
    if not (0 < future_weeks <= MAX_FUTURE_WEEKS):
        return {CONF_FUTURE_WEEKS: "invalid_range"}
    if len(feed_name(data)) > MAX_FEED_NAME_LENGTH:
        return {CONF_FEED_NAME: "feed_name_too_long"}

    filter_mode, filter_regex, filter_fields, _, event_type = filter_settings(data)
    if filter_mode not in VALID_FILTER_MODES:
        return {CONF_FILTER_MODE: "invalid_filter_mode"}
    if regex_error := validate_filter_regex(filter_mode, filter_regex):
        return {CONF_FILTER_REGEX: regex_error}
    if any(field not in VALID_FILTER_FIELDS for field in filter_fields) or (
        filter_mode != FILTER_MODE_NONE and not filter_fields
    ):
        return {CONF_FILTER_FIELDS: "invalid_filter_fields"}
    if event_type not in VALID_EVENT_TYPES:
        return {CONF_EVENT_TYPE_FILTER: "invalid_event_type"}

    try:
        interval = refresh_interval(data)
    except (TypeError, ValueError):
        return {CONF_REFRESH_INTERVAL: "invalid_refresh_interval"}
    if not (0 <= interval <= MAX_REFRESH_INTERVAL):
        return {CONF_REFRESH_INTERVAL: "invalid_refresh_interval"}

    try:
        timed_alarm, all_day_days, all_day_time = alarm_settings(data)
    except (TypeError, ValueError):
        return {CONF_TIMED_ALARM_MINUTES: "invalid_timed_alarm"}
    if not (-1 <= timed_alarm <= MAX_ALARM_MINUTES):
        return {CONF_TIMED_ALARM_MINUTES: "invalid_timed_alarm"}
    if not (-1 <= all_day_days <= MAX_ALL_DAY_ALARM_DAYS_BEFORE):
        return {CONF_ALL_DAY_ALARM_DAYS_BEFORE: "invalid_all_day_alarm_days"}
    if (all_day_days >= 0 or all_day_time) and not re.fullmatch(
        r"([01]\d|2[0-3]):[0-5]\d", all_day_time
    ):
        return {CONF_ALL_DAY_ALARM_TIME: "invalid_all_day_alarm_time"}
    return {}


def _same_feed_config(existing_data: Mapping[str, Any], candidate_data: Mapping[str, Any]) -> bool:
    """Compare full feed selection, filters, and privacy options for duplicate detection."""
    existing_mode, existing_entities = calendar_selection(existing_data)
    candidate_mode, candidate_entities = calendar_selection(candidate_data)
    existing_filter = filter_settings(existing_data)
    candidate_filter = filter_settings(candidate_data)
    return (
        existing_mode == candidate_mode
        and set(existing_entities) == set(candidate_entities)
        and existing_filter[0] == candidate_filter[0]
        and existing_filter[1] == candidate_filter[1]
        and set(existing_filter[2]) == set(candidate_filter[2])
        and existing_filter[3] == candidate_filter[3]
        and existing_filter[4] == candidate_filter[4]
        and privacy_settings(existing_data) == privacy_settings(candidate_data)
        and alarm_settings(existing_data) == alarm_settings(candidate_data)
    )


def _normalized_entry_data(
    user_input: Mapping[str, Any],
    *,
    secret: str,
    base_data: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build normalized config entry data from validated user input."""
    mode, entity_ids = calendar_selection(user_input)
    history_weeks, future_weeks = calendar_range(user_input)
    custom_name = feed_name(user_input)
    filter_mode, filter_regex, filter_fields, case_sensitive, event_type = filter_settings(
        user_input
    )
    strip_description, strip_location, prefix_calendar_name = privacy_settings(user_input)
    timed_alarm, all_day_days, all_day_time = alarm_settings(user_input)
    interval = refresh_interval(user_input)

    data = {
        **(base_data or {}),
        CONF_GEOCODING_URL: user_input.get(CONF_GEOCODING_URL, "").strip(),
        CONF_CALENDAR_ENTITY_IDS: entity_ids,
        CONF_SELECTION_MODE: mode,
        CONF_HISTORY_WEEKS: history_weeks,
        CONF_FUTURE_WEEKS: future_weeks,
        CONF_FEED_NAME: custom_name,
        CONF_FILTER_MODE: filter_mode,
        CONF_FILTER_REGEX: filter_regex,
        CONF_FILTER_FIELDS: filter_fields,
        CONF_FILTER_CASE_SENSITIVE: case_sensitive,
        CONF_EVENT_TYPE_FILTER: event_type,
        CONF_STRIP_DESCRIPTION: strip_description,
        CONF_STRIP_LOCATION: strip_location,
        CONF_PREFIX_CALENDAR_NAME: prefix_calendar_name,
        CONF_TIMED_ALARM_MINUTES: timed_alarm,
        CONF_ALL_DAY_ALARM_DAYS_BEFORE: all_day_days,
        CONF_ALL_DAY_ALARM_TIME: all_day_time,
        CONF_REFRESH_INTERVAL: interval,
        CONF_SECRET: secret,
    }
    data.pop(CONF_CALENDAR_ENTITY_ID, None)
    return data


class ICalendarConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iCalendar API."""

    VERSION = 1

    async def async_on_create_entry(self, result):
        """Continue to options flow after setup to show the generated feed URL."""
        if self.source != SOURCE_USER:
            return result
        options_result = await self.hass.config_entries.options.async_init(result["result"].entry_id)
        result["next_flow"] = (FlowType.OPTIONS_FLOW, options_result["flow_id"])
        return result

    async def async_step_user(self, user_input: Mapping[str, Any] | None = None):
        """Handle initial setup."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mode, entity_ids = calendar_selection(user_input)
            custom_name = feed_name(user_input)
            if errors := _selection_errors(self.hass, user_input):
                return self.async_show_form(
                    step_id="user", data_schema=_build_user_schema(user_input), errors=errors
                )

            data = _normalized_entry_data(user_input, secret=_generate_secret())
            for entry in self._async_current_entries():
                if _same_feed_config(entry.data, data):
                    return self.async_abort(reason="already_configured")

            return self.async_create_entry(
                title=_title_for_selection(mode, entity_ids, custom_name),
                data=data,
            )

        return self.async_show_form(step_id="user", data_schema=_build_user_schema(), errors=errors)

    async def async_step_reconfigure(self, user_input: Mapping[str, Any] | None = None):
        """Handle reconfiguration from the UI."""
        entry = self._get_reconfigure_entry()
        existing_secret = entry.data.get(CONF_SECRET, "")
        local_url, external_url = _build_feed_urls(self.hass, entry.entry_id, existing_secret)

        if user_input is not None:
            mode, entity_ids = calendar_selection(user_input)
            custom_name = feed_name(user_input)
            if errors := _selection_errors(self.hass, user_input):
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_build_reconfigure_schema(entry, user_input),
                    errors=errors,
                    description_placeholders={
                        "url_block": _build_urls_text(local_url, external_url),
                    },
                )

            new_secret = user_input.get(CONF_SECRET)
            secret_cleared = CONF_SECRET in user_input and (new_secret is None or new_secret == "")
            if new_secret and not _is_secret_valid(new_secret):
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_build_reconfigure_schema(entry, user_input),
                    errors={CONF_SECRET: "invalid_secret"},
                    description_placeholders={
                        "url_block": _build_urls_text(local_url, external_url),
                    },
                )

            final_secret = _generate_secret() if secret_cleared else (new_secret or existing_secret)
            updated_data = _normalized_entry_data(
                user_input,
                secret=final_secret,
                base_data=entry.data,
            )
            for existing_entry in self._async_current_entries():
                if (
                    existing_entry.entry_id != entry.entry_id
                    and _same_feed_config(existing_entry.data, updated_data)
                ):
                    return self.async_abort(reason="already_configured")

            self.hass.config_entries.async_update_entry(
                entry,
                title=_title_for_selection(mode, entity_ids, custom_name),
                data=updated_data,
            )
            await self.hass.config_entries.async_reload(entry.entry_id)
            if secret_cleared:
                new_local_url, new_external_url = _build_feed_urls(
                    self.hass, entry.entry_id, final_secret
                )
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=_build_reconfigure_schema(entry, updated_data),
                    description_placeholders={
                        "url_block": _build_urls_text(new_local_url, new_external_url),
                    },
                )
            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_build_reconfigure_schema(entry),
            description_placeholders={
                "url_block": _build_urls_text(local_url, external_url),
            },
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        """Get options flow."""
        return ICalendarOptionsFlow()


class ICalendarOptionsFlow(config_entries.OptionsFlow):
    """Handle options for iCalendar API."""

    async def async_step_init(self, user_input: Mapping[str, Any] | None = None):
        """Manage options."""
        errors: dict[str, str] = {}
        existing_secret = self.config_entry.data.get(CONF_SECRET, "")
        local_url, external_url = _build_feed_urls(
            self.hass, self.config_entry.entry_id, existing_secret
        )

        if user_input is not None:
            mode, entity_ids = calendar_selection(user_input)
            custom_name = feed_name(user_input)
            errors = _selection_errors(self.hass, user_input)
            new_secret = user_input.get(CONF_SECRET)
            secret_cleared = CONF_SECRET in user_input and (new_secret is None or new_secret == "")
            if new_secret and not _is_secret_valid(new_secret):
                errors[CONF_SECRET] = "invalid_secret"

            final_secret = _generate_secret() if secret_cleared else (new_secret or existing_secret)
            updated_data = _normalized_entry_data(
                user_input,
                secret=final_secret,
                base_data=self.config_entry.data,
            )
            if not errors:
                for entry in self.hass.config_entries.async_entries(DOMAIN):
                    if (
                        entry.entry_id != self.config_entry.entry_id
                        and _same_feed_config(entry.data, updated_data)
                    ):
                        errors["base"] = "already_configured"
                        break
            if errors:
                return self.async_show_form(
                    step_id="init",
                    data_schema=_build_options_schema(self.config_entry, user_input),
                    errors=errors,
                    description_placeholders={
                        "url_block": _build_urls_text(local_url, external_url),
                    },
                )
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                title=_title_for_selection(mode, entity_ids, custom_name),
                data=updated_data,
            )
            await self.hass.config_entries.async_reload(self.config_entry.entry_id)
            if secret_cleared:
                new_local_url, new_external_url = _build_feed_urls(
                    self.hass, self.config_entry.entry_id, final_secret
                )
                return self.async_show_form(
                    step_id="init",
                    data_schema=_build_options_schema(self.config_entry, updated_data),
                    description_placeholders={
                        "url_block": _build_urls_text(new_local_url, new_external_url),
                    },
                )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_options_schema(self.config_entry),
            description_placeholders={
                "url_block": _build_urls_text(local_url, external_url),
            },
        )


def _build_user_schema(user_input: Mapping[str, Any] | None = None) -> vol.Schema:
    """Build the calendar selection and filtering schema."""
    data = user_input or {}
    mode, entity_ids = calendar_selection(data)
    history_weeks, future_weeks = calendar_range(data)
    filter_mode, filter_regex, filter_fields, case_sensitive, event_type = filter_settings(data)
    strip_description, strip_location, prefix_calendar_name = privacy_settings(data)
    timed_alarm, all_day_days, all_day_time = alarm_settings(data)
    interval = refresh_interval(data)

    return vol.Schema({
        vol.Required(CONF_SELECTION_MODE, default=mode): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[MODE_INCLUDE, MODE_EXCLUDE], translation_key="selection_mode"
            )
        ),
        vol.Required(CONF_CALENDAR_ENTITY_IDS, default=entity_ids): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["calendar"], multiple=True)
        ),
        vol.Optional(CONF_FEED_NAME, default=feed_name(data)): vol.All(
            str, vol.Length(max=MAX_FEED_NAME_LENGTH)
        ),
        vol.Optional(CONF_FILTER_MODE, default=filter_mode): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(VALID_FILTER_MODES), translation_key="filter_mode"
            )
        ),
        vol.Optional(CONF_FILTER_REGEX, default=filter_regex): str,
        vol.Optional(CONF_FILTER_FIELDS, default=filter_fields): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(VALID_FILTER_FIELDS),
                multiple=True,
                translation_key="filter_fields",
            )
        ),
        vol.Optional(CONF_FILTER_CASE_SENSITIVE, default=case_sensitive): bool,
        vol.Optional(CONF_EVENT_TYPE_FILTER, default=event_type): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(VALID_EVENT_TYPES), translation_key="event_type_filter"
            )
        ),
        vol.Optional(CONF_STRIP_DESCRIPTION, default=strip_description): bool,
        vol.Optional(CONF_STRIP_LOCATION, default=strip_location): bool,
        vol.Optional(CONF_PREFIX_CALENDAR_NAME, default=prefix_calendar_name): bool,
        vol.Optional(CONF_TIMED_ALARM_MINUTES, default=timed_alarm): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=-1, max=MAX_ALARM_MINUTES, step=1, mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        ),
        vol.Optional(CONF_ALL_DAY_ALARM_DAYS_BEFORE, default=all_day_days): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=-1, max=MAX_ALL_DAY_ALARM_DAYS_BEFORE, step=1,
                mode=selector.NumberSelectorMode.BOX, unit_of_measurement="days",
            )
        ),
        vol.Optional(CONF_ALL_DAY_ALARM_TIME, default=all_day_time): str,
        vol.Optional(CONF_GEOCODING_URL, default=data.get(CONF_GEOCODING_URL, "")): str,
        vol.Required(CONF_HISTORY_WEEKS, default=history_weeks): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=MAX_HISTORY_WEEKS, step=1, mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="weeks",
            )
        ),
        vol.Required(CONF_FUTURE_WEEKS, default=future_weeks): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1, max=MAX_FUTURE_WEEKS, step=1, mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="weeks",
            )
        ),
        vol.Optional(CONF_REFRESH_INTERVAL, default=interval): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0, max=MAX_REFRESH_INTERVAL, step=1, mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        ),
    })


def _build_reconfigure_schema(
    entry: config_entries.ConfigEntry,
    user_input: Mapping[str, Any] | None = None,
) -> vol.Schema:
    """Build reconfigure schema with current entry or submitted values."""
    data = entry.data if user_input is None else user_input
    return _build_user_schema(data).extend({
        vol.Optional(CONF_SECRET, default=data.get(CONF_SECRET, "")): str,
    })


def _build_options_schema(
    entry: config_entries.ConfigEntry,
    user_input: Mapping[str, Any] | None = None,
) -> vol.Schema:
    """Build settings with the current selection or submitted values."""
    data = entry.data if user_input is None else user_input
    return _build_user_schema(data).extend({
        vol.Optional(CONF_SECRET, default=data.get(CONF_SECRET, "")): str,
    })
