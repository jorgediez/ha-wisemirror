"""Tests for the entity platforms: state mapping and the commands they send."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .harness import MockConfigEntry

PREFIX = "wisemirror_2m09_ceb8"


@pytest.fixture
async def setup_mirror(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> MagicMock:
    await hass.config.async_update(latitude=42.6, longitude=-5.5)  # no location push
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return mock_device


async def _call(
    hass: HomeAssistant, domain: str, service: str, entity: str, **data: Any
) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity, **data}, blocking=True
    )


async def test_states(hass: HomeAssistant, setup_mirror: MagicMock) -> None:
    expected = {
        f"number.{PREFIX}_display_brightness": "80",
        f"number.{PREFIX}_night_brightness": "10",
        f"switch.{PREFIX}_night_mode": "off",
        f"switch.{PREFIX}_two_day_weather": "off",
        f"switch.{PREFIX}_24_hour_clock": "on",
        f"switch.{PREFIX}_day_month_date_order": "on",
        f"select.{PREFIX}_temperature_unit": "celsius",
        f"select.{PREFIX}_weather_source": "auto",
        f"time.{PREFIX}_night_mode_start": "22:30:00",
        f"time.{PREFIX}_night_mode_end": "07:00:00",
        f"sensor.{PREFIX}_weather_location": "León",
        f"binary_sensor.{PREFIX}_connectivity": "on",
    }
    for entity_id, value in expected.items():
        assert hass.states.get(entity_id).state == value, entity_id
    # disabled by default
    assert hass.states.get(f"switch.{PREFIX}_key_tone") is None
    assert hass.states.get(f"sensor.{PREFIX}_ip_address") is None


@pytest.mark.parametrize(
    ("domain", "service", "entity", "data", "setter", "args"),
    [
        (
            "number",
            "set_value",
            "number.{p}_display_brightness",
            {"value": 35},
            "set_brightness",
            (35,),
        ),
        (
            "number",
            "set_value",
            "number.{p}_night_brightness",
            {"value": 3},
            "set_night_brightness",
            (3,),
        ),
        ("switch", "turn_on", "switch.{p}_night_mode", {}, "set_night_mode", (True,)),
        ("switch", "turn_off", "switch.{p}_24_hour_clock", {}, "set_hour24", (False,)),
        (
            "switch",
            "turn_off",
            "switch.{p}_day_month_date_order",
            {},
            "set_daymonth",
            (False,),
        ),
        # weather command keeps the current server (Auto = 255)
        (
            "switch",
            "turn_on",
            "switch.{p}_two_day_weather",
            {},
            "set_weather",
            (True, 255),
        ),
        # ... and the current two-day flag (off); "no4" is raw 0
        (
            "select",
            "select_option",
            "select.{p}_weather_source",
            {"option": "no4"},
            "set_weather",
            (False, 0),
        ),
        (
            "select",
            "select_option",
            "select.{p}_temperature_unit",
            {"option": "fahrenheit"},
            "set_unit_celsius",
            (False,),
        ),
        # the night window is sent whole: the untouched end stays 07:00
        (
            "time",
            "set_value",
            "time.{p}_night_mode_start",
            {"time": "23:15:00"},
            "set_night_time",
            (23, 15, 7, 0),
        ),
        (
            "time",
            "set_value",
            "time.{p}_night_mode_end",
            {"time": "06:45:00"},
            "set_night_time",
            (22, 30, 6, 45),
        ),
    ],
)
async def test_commands(
    hass: HomeAssistant,
    setup_mirror: MagicMock,
    domain: str,
    service: str,
    entity: str,
    data: dict[str, Any],
    setter: str,
    args: tuple[Any, ...],
) -> None:
    polls = setup_mirror.poll.call_count
    await _call(hass, domain, service, entity.format(p=PREFIX), **data)
    getattr(setup_mirror, setter).assert_called_once_with(*args)
    assert setup_mirror.poll.call_count == polls + 1  # state refreshed after write


async def test_command_not_acknowledged(
    hass: HomeAssistant, setup_mirror: MagicMock
) -> None:
    setup_mirror.set_brightness.return_value = False
    with pytest.raises(HomeAssistantError) as err:
        await _call(
            hass, "number", "set_value", f"number.{PREFIX}_display_brightness", value=50
        )
    assert err.value.translation_key == "command_not_acknowledged"


async def test_fahrenheit_unit(
    hass: HomeAssistant,
    mock_device: MagicMock,
    state: dict[str, Any],
    config_entry: MockConfigEntry,
) -> None:
    state["unit"] = 0
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(f"select.{PREFIX}_temperature_unit").state == "fahrenheit"


# Each of these writes a command that also carries another setting, read by the
# same poll reply. The weather settings are not the defaults (off, Auto), so a
# default sent in their place shows.
WEATHER = {"two_day": True, "server": "no2", "server_raw": 2}
HALF_WRITES = [
    pytest.param(
        ("two_day", "today_weather", "server", "server_raw"),
        ("switch", "turn_off", "switch.{p}_two_day_weather", {}),
        "set_weather",
        (False, 2),
        id="two-day",
    ),
    pytest.param(
        ("two_day", "today_weather", "server", "server_raw"),
        ("select", "select_option", "select.{p}_weather_source", {"option": "no4"}),
        "set_weather",
        (True, 0),
        id="weather-source",
    ),
    pytest.param(
        ("night_on", "night_start", "night_end", "night_light"),
        ("time", "set_value", "time.{p}_night_mode_start", {"time": "23:15:00"}),
        "set_night_time",
        (23, 15, 7, 0),
        id="night-start",
    ),
    pytest.param(
        ("night_on", "night_start", "night_end", "night_light"),
        ("time", "set_value", "time.{p}_night_mode_end", {"time": "06:45:00"}),
        "set_night_time",
        (22, 30, 6, 45),
        id="night-end",
    ),
]


async def _poll_without(
    setup_mirror: MagicMock, config_entry: MockConfigEntry, keys: tuple[str, ...]
) -> dict[str, Any]:
    """Make the last poll miss keys, as when one reply of a poll is lost."""
    full = {**setup_mirror.poll(), **WEATHER}
    partial = {k: v for k, v in full.items() if k not in keys}
    setup_mirror.poll.side_effect = lambda: dict(partial)
    await config_entry.runtime_data.async_refresh()
    assert not keys & config_entry.runtime_data.data.keys()
    return full


@pytest.mark.parametrize(("missing", "call", "setter", "args"), HALF_WRITES)
async def test_half_write_after_a_partial_poll_reads_again(
    hass: HomeAssistant,
    setup_mirror: MagicMock,
    config_entry: MockConfigEntry,
    missing: tuple[str, ...],
    call: tuple[str, str, str, dict[str, Any]],
    setter: str,
    args: tuple[Any, ...],
) -> None:
    """The other half is read again before writing, not replaced by a default."""
    full = await _poll_without(setup_mirror, config_entry, missing)
    setup_mirror.poll.side_effect = lambda: dict(full)  # the next read gets it
    domain, service, entity, data = call
    await _call(hass, domain, service, entity.format(p=PREFIX), **data)
    getattr(setup_mirror, setter).assert_called_once_with(*args)


@pytest.mark.parametrize(("missing", "call", "setter", "args"), HALF_WRITES)
async def test_half_write_is_refused_while_the_other_half_is_unknown(
    hass: HomeAssistant,
    setup_mirror: MagicMock,
    config_entry: MockConfigEntry,
    missing: tuple[str, ...],
    call: tuple[str, str, str, dict[str, Any]],
    setter: str,
    args: tuple[Any, ...],
) -> None:
    """Without the other half, nothing is sent: a guess would overwrite it."""
    await _poll_without(setup_mirror, config_entry, missing)
    domain, service, entity, data = call
    with pytest.raises(HomeAssistantError) as err:
        await _call(hass, domain, service, entity.format(p=PREFIX), **data)
    assert err.value.translation_key == "current_state_unknown"
    getattr(setup_mirror, setter).assert_not_called()
