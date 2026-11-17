"""Regression coverage for changing calendar selections from settings."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.icalendar.config_flow import ICalendarOptionsFlow
from homeassistant.helpers import selector


@pytest.fixture
def settings(monkeypatch):
    for name in ('SelectSelector', 'SelectSelectorConfig', 'EntitySelector', 'EntitySelectorConfig',
                 'NumberSelector', 'NumberSelectorConfig'):
        monkeypatch.setattr(selector, name, Mock(return_value=lambda value: value), raising=False)
    entry = SimpleNamespace(entry_id='feed', data={
        'calendar_entity_id': 'calendar.original', 'secret': 'a' * 24, 'geocoding_url': '',
    })
    flow = ICalendarOptionsFlow()
    flow.config_entry = entry
    flow.hass = SimpleNamespace(
        config=SimpleNamespace(internal_url='https://ha.local', external_url=None),
        states=SimpleNamespace(get=lambda entity: object() if entity != 'calendar.missing' else None),
        config_entries=SimpleNamespace(
            async_entries=Mock(return_value=[entry]),
            async_update_entry=Mock(), async_reload=AsyncMock(),
        ),
    )
    flow.async_show_form = Mock(side_effect=lambda **kwargs: kwargs)
    flow.async_create_entry = Mock(return_value={'type': 'create_entry'})
    return flow


def defaults(result):
    return {key.schema: key.default() for key in result['data_schema'].schema}


def test_settings_shows_legacy_selection_and_url(settings):
    result = asyncio.run(settings.async_step_init())
    assert defaults(result) == {
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'secret': 'a' * 24, 'geocoding_url': '', 'history_weeks': 4, 'future_weeks': 52,
        'feed_name': '', 'filter_mode': 'none', 'filter_regex': '', 'filter_fields': ['summary'], 'filter_case_sensitive': False, 'event_type_filter': 'all', 'strip_description': False, 'strip_location': False, 'prefix_calendar_name': False, 'timed_alarm_minutes': -1, 'all_day_alarm_days_before': -1, 'all_day_alarm_time': '09:00', 'refresh_interval': 60,
    }
    assert 'https://ha.local/api/ics/feed/' in result['description_placeholders']['url_block']


@pytest.mark.parametrize('mode,entities,secret', [
    ('include', ['calendar.changed'], 'a' * 24),
    ('exclude', [], 'b' * 24),
])
def test_settings_saves_selection_and_reloads(settings, mode, entities, secret):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': mode, 'calendar_entity_ids': entities, 'secret': secret,
    }))
    assert result['type'] == 'create_entry'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs
    assert saved['data'] == {
        'selection_mode': mode, 'calendar_entity_ids': entities,
        'secret': secret or 'a' * 24, 'geocoding_url': '',
        'history_weeks': 4, 'future_weeks': 52, 'feed_name': '', 'filter_mode': 'none', 'filter_regex': '', 'filter_fields': ['summary'], 'filter_case_sensitive': False, 'event_type_filter': 'all', 'strip_description': False, 'strip_location': False, 'prefix_calendar_name': False, 'timed_alarm_minutes': -1, 'all_day_alarm_days_before': -1, 'all_day_alarm_time': '09:00', 'refresh_interval': 60,
    }
    assert mode in saved['title']
    settings.hass.config_entries.async_reload.assert_awaited_once_with('feed')


def test_settings_saves_custom_history_and_future_range(settings):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'history_weeks': 52, 'future_weeks': 8,
    }))
    assert result['type'] == 'create_entry'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs['data']
    assert saved['history_weeks'] == 52
    assert saved['future_weeks'] == 8


def test_settings_saves_custom_feed_name_and_uses_it_as_title(settings):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'feed_name': '  🏠 Family  ',
    }))
    assert result['type'] == 'create_entry'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs
    assert saved['data']['feed_name'] == '🏠 Family'
    assert saved['title'] == '🏠 Family'


def test_clearing_feed_name_reverts_to_generated_title(settings):
    settings.config_entry.data['feed_name'] = '🏠 Family'
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'feed_name': '',
    }))
    assert result['type'] == 'create_entry'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs
    assert saved['data']['feed_name'] == ''
    assert saved['title'] == 'iCalendar API (include: calendar.original)'


@pytest.mark.parametrize('mode,entities,secret,error', [
    ('include', [], '', 'no_calendars'),
    ('include', ['calendar.missing'], '', 'entity_not_found'),
    ('invalid', [], '', 'invalid_selection_mode'),
    ('exclude', [], 'short', 'invalid_secret'),
])
def test_invalid_settings_preserve_input_without_saving(settings, mode, entities, secret, error):
    data = {'selection_mode': mode, 'calendar_entity_ids': entities, 'secret': secret}
    result = asyncio.run(settings.async_step_init(data))
    assert error in result['errors'].values()
    assert defaults(result) == {
        **data, 'geocoding_url': '', 'history_weeks': 4, 'future_weeks': 52, 'feed_name': '',
        'filter_mode': 'none', 'filter_regex': '', 'filter_fields': ['summary'], 'filter_case_sensitive': False, 'event_type_filter': 'all', 'strip_description': False, 'strip_location': False, 'prefix_calendar_name': False, 'timed_alarm_minutes': -1, 'all_day_alarm_days_before': -1, 'all_day_alarm_time': '09:00', 'refresh_interval': 60,
    }
    settings.hass.config_entries.async_update_entry.assert_not_called()
    settings.hass.config_entries.async_reload.assert_not_awaited()


def test_feed_name_too_long_preserves_input_without_saving(settings):
    data = {
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'feed_name': 'x' * 101,
    }
    result = asyncio.run(settings.async_step_init(data))
    assert 'feed_name_too_long' in result['errors'].values()
    settings.hass.config_entries.async_update_entry.assert_not_called()


@pytest.mark.parametrize('history_weeks,future_weeks', [
    (-1, 52),
    (4, 0),
    (4, -5),
    (600, 52),
    (4, 600),
])
def test_invalid_range_preserves_input_without_saving(settings, history_weeks, future_weeks):
    data = {
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'history_weeks': history_weeks, 'future_weeks': future_weeks,
    }
    result = asyncio.run(settings.async_step_init(data))
    assert 'invalid_range' in result['errors'].values()
    settings.hass.config_entries.async_update_entry.assert_not_called()


def test_duplicate_selection_is_rejected(settings):
    settings.hass.config_entries.async_entries.return_value.append(SimpleNamespace(
        entry_id='other', data={'selection_mode': 'exclude', 'calendar_entity_ids': []},
    ))
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'exclude', 'calendar_entity_ids': [],
    }))
    assert result['errors'] == {'base': 'already_configured'}
    settings.hass.config_entries.async_update_entry.assert_not_called()


def test_settings_saves_geocoding_endpoint(settings):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'geocoding_url': 'https://geo.example/search',
    }))
    assert result['type'] == 'create_entry'
    assert settings.hass.config_entries.async_update_entry.call_args.kwargs['data']['geocoding_url'] == 'https://geo.example/search'


@pytest.mark.parametrize('url', ['ftp://geo/search', 'https://', 'https://user:pass@geo/search',
                                'https://geo/search?q=test', 'https://geo/search#fragment'])
def test_invalid_geocoding_endpoint(settings, url):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'geocoding_url': url,
    }))
    assert result['errors'] == {'geocoding_url': 'invalid_geocoding_url'}
    settings.hass.config_entries.async_update_entry.assert_not_called()


def test_regex_filter_settings_and_validation(settings):
    invalid = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'filter_mode': 'include', 'filter_regex': '[broken',
    }))
    assert invalid['errors'] == {'filter_regex': 'invalid_regex'}
    settings.hass.config_entries.async_update_entry.assert_not_called()

    missing_pattern = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'filter_mode': 'exclude', 'filter_regex': '',
    }))
    assert missing_pattern['errors'] == {'filter_regex': 'regex_required'}

    valid = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'filter_mode': 'include', 'filter_regex': r'^Work:',
        'filter_fields': ['summary', 'description'],
        'filter_case_sensitive': True,
        'event_type_filter': 'timed',
        'strip_description': True,
        'strip_location': True,
        'prefix_calendar_name': True,
        'refresh_interval': 30,
    }))
    assert valid['type'] == 'create_entry'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs['data']
    assert saved['filter_mode'] == 'include'
    assert saved['filter_regex'] == r'^Work:'
    assert saved['filter_fields'] == ['summary', 'description']
    assert saved['filter_case_sensitive'] is True
    assert saved['event_type_filter'] == 'timed'
    assert saved['strip_description'] is True
    assert saved['strip_location'] is True
    assert saved['prefix_calendar_name'] is True
    assert saved['refresh_interval'] == 30


def test_same_calendars_allowed_when_filter_differs(settings):
    settings.hass.config_entries.async_entries.return_value.append(SimpleNamespace(
        entry_id='other', data={
            'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
            'filter_mode': 'include', 'filter_regex': '^Work',
        },
    ))
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'filter_mode': 'exclude', 'filter_regex': '^Private',
    }))
    assert result['type'] == 'create_entry'


def test_default_alarm_settings_and_validation(settings):
    bad_timed = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'timed_alarm_minutes': -2,
    }))
    assert bad_timed['errors'] == {'timed_alarm_minutes': 'invalid_timed_alarm'}

    bad_days = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'all_day_alarm_days_before': 31,
    }))
    assert bad_days['errors'] == {'all_day_alarm_days_before': 'invalid_all_day_alarm_days'}

    bad_time = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'all_day_alarm_days_before': 1, 'all_day_alarm_time': '25:99',
    }))
    assert bad_time['errors'] == {'all_day_alarm_time': 'invalid_all_day_alarm_time'}

    valid = asyncio.run(settings.async_step_init({
        'selection_mode': 'include', 'calendar_entity_ids': ['calendar.original'],
        'timed_alarm_minutes': 15,
        'all_day_alarm_days_before': 1,
        'all_day_alarm_time': '09:00',
        'strip_description': True,
    }))
    assert valid['type'] == 'create_entry'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs['data']
    assert saved['timed_alarm_minutes'] == 15
    assert saved['all_day_alarm_days_before'] == 1
    assert saved['all_day_alarm_time'] == '09:00'
    assert saved['strip_description'] is True


def test_clearing_secret_regenerates_key_and_reopens_options(settings):
    result = asyncio.run(settings.async_step_init({
        'selection_mode': 'include',
        'calendar_entity_ids': ['calendar.changed'],
        'secret': '',
    }))
    assert result['step_id'] == 'init'
    saved = settings.hass.config_entries.async_update_entry.call_args.kwargs['data']
    new_secret = saved['secret']
    assert new_secret != 'a' * 24
    assert len(new_secret) >= 20
    assert defaults(result)['secret'] == new_secret
    assert f'https://ha.local/api/ics/feed/{new_secret}.ics' in result['description_placeholders']['url_block']
    settings.hass.config_entries.async_reload.assert_awaited_once_with('feed')
