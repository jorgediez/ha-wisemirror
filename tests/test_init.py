"""Tests for setup, location sync, services and IP relocation."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.wisemirror.const import (
    CONF_HOST,
    CONF_USE_HA_LOCATION,
    DOMAIN,
    SERVICE_SET_LOCATION,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import device_registry as dr, entity_registry as er

from .conftest import BSSID, HOST


def _device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return device


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_setup_and_unload(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    assert config_entry.state is ConfigEntryState.LOADED

    device = _device(hass, config_entry)
    assert (DOMAIN, BSSID) in device.identifiers
    assert device.name == "WiseMirror 2M09 (CEB8)"
    assert device.model == "2M09"
    assert device.sw_version == "V1.9.250215"
    assert (dr.CONNECTION_NETWORK_MAC, BSSID) in device.connections

    assert (
        hass.states.get("sensor.wisemirror_2m09_ceb8_indoor_temperature").state
        == "25.0"
    )
    assert hass.states.get("sensor.wisemirror_2m09_ceb8_indoor_humidity").state == "45"

    assert await hass.config_entries.async_unload(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_not_ready(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    mock_device.poll.side_effect = ConnectionError
    mock_device.discover.return_value = []
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_humidity_disabled_by_default_without_sensor(
    hass: HomeAssistant,
    mock_device: MagicMock,
    state: dict[str, Any],
    config_entry: MockConfigEntry,
) -> None:
    state["has_humidity_sensor"] = False
    state["humidity"] = None
    await _setup(hass, config_entry)
    entity_id = "sensor.wisemirror_2m09_ceb8_indoor_humidity"
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity_id) is None


async def test_follows_ha_location(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await hass.config.async_update(
        latitude=40.4168, longitude=-3.7038, location_name="Casa"
    )
    await _setup(hass, config_entry)
    mock_device.set_location.assert_called_once_with("Casa", 40.4168, -3.7038)

    mock_device.set_location.reset_mock()
    await hass.config.async_update(latitude=41.0, longitude=-4.0)
    await hass.async_block_till_done()
    mock_device.set_location.assert_called_once_with("Casa", 41.0, -4.0)


async def test_location_already_matches(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await hass.config.async_update(latitude=42.6, longitude=-5.5)
    await _setup(hass, config_entry)
    mock_device.set_location.assert_not_called()


async def test_location_sync_disabled(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        title=config_entry.title,
        unique_id=config_entry.unique_id,
        data=dict(config_entry.data),
        options={CONF_USE_HA_LOCATION: False},
    )
    await hass.config.async_update(latitude=40.4168, longitude=-3.7038)
    await _setup(hass, config_entry)
    await hass.config.async_update(latitude=41.0, longitude=-4.0)
    await hass.async_block_till_done()
    mock_device.set_location.assert_not_called()


async def test_set_location_service(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await hass.config.async_update(latitude=42.6, longitude=-5.5)
    await _setup(hass, config_entry)
    device = _device(hass, config_entry)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_LOCATION,
        {"device_id": device.id, "name": "Madrid", "latitude": 40.4, "longitude": -3.7},
        blocking=True,
    )
    mock_device.set_location.assert_called_once_with("Madrid", 40.4, -3.7)

    # targeting through an entity of the mirror works too
    mock_device.set_location.reset_mock()
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_LOCATION,
        {
            "entity_id": "sensor.wisemirror_2m09_ceb8_indoor_temperature",
            "name": "Madrid",
            "latitude": 40.4,
            "longitude": -3.7,
        },
        blocking=True,
    )
    mock_device.set_location.assert_called_once()


async def test_set_location_service_no_target(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_LOCATION,
            {"device_id": "nope", "name": "X", "latitude": 1, "longitude": 2},
            blocking=True,
        )


async def test_relocates_after_ip_change(
    hass: HomeAssistant,
    mock_device: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data

    polled_hosts: list[str] = []
    good = mock_device.poll.side_effect

    def poll() -> dict[str, Any]:
        polled_hosts.append(coordinator.device.host)
        if coordinator.device.host == HOST:
            raise ConnectionError("gone")
        return good()

    mock_device.poll.side_effect = poll
    mock_device.discover.return_value = [
        {"bssid": BSSID, "address": "192.168.1.77", "model": "2M09"}
    ]
    freezer.tick(61)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert polled_hosts == [HOST, "192.168.1.77"]
    assert coordinator.last_update_success
    assert config_entry.data[CONF_HOST] == "192.168.1.77"
    assert config_entry.state is ConfigEntryState.LOADED


async def test_offline_marks_entities_unavailable(
    hass: HomeAssistant,
    mock_device: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    await _setup(hass, config_entry)
    mock_device.poll.side_effect = ConnectionError("gone")
    mock_device.discover.return_value = []
    freezer.tick(61)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    assert (
        hass.states.get("sensor.wisemirror_2m09_ceb8_indoor_temperature").state
        == "unavailable"
    )
    assert (
        hass.states.get("binary_sensor.wisemirror_2m09_ceb8_connectivity").state
        == "off"
    )


async def test_a_failed_poll_is_reported_in_the_users_language(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await _setup(hass, config_entry)
    mock_device.poll.side_effect = ConnectionError("gone")
    mock_device.discover.return_value = []

    coordinator = config_entry.runtime_data
    await coordinator.async_refresh()

    error = coordinator.last_exception
    assert error.translation_key == "update_failed"
    assert error.translation_placeholders == {"host": HOST, "error": "gone"}
