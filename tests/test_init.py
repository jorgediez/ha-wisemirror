"""Tests for setup, location sync, services and IP relocation."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest

from custom_components.wisemirror.const import (
    CONF_BSSID,
    CONF_HOST,
    CONF_USE_HA_LOCATION,
    DOMAIN,
    SERVICE_SET_LOCATION,
)
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import (
    area_registry as ar,
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
    floor_registry as fr,
    label_registry as lr,
)

from .conftest import BSSID, HOST, SETTERS
from .harness import (
    MockConfigEntry,
    async_fire_time_changed,
)


def _device(hass: HomeAssistant, entry: MockConfigEntry) -> dr.DeviceEntry:
    (device,) = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    return device


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _second_mirror() -> MockConfigEntry:
    """Another mirror, to check an action only reaches the one it targets."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="WiseMirror 2M09 (0001)",
        unique_id="30:30:f9:00:00:01",
        data={CONF_HOST: "192.168.1.245", CONF_BSSID: "30:30:f9:00:00:01"},
    )


def _following(entry: MockConfigEntry, follow: bool = True) -> MockConfigEntry:
    """Return the entry with "Follow Home Assistant's home location" set."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=entry.title,
        unique_id=entry.unique_id,
        data=dict(entry.data),
        options={CONF_USE_HA_LOCATION: follow},
    )


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


async def test_nothing_is_written_by_default(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Following Home Assistant's location is opt-in.

    Until the user turns it on, setting up a mirror or moving Home Assistant's
    home writes nothing to it, so the city picked in the app stays.
    """
    await hass.config.async_update(latitude=40.4168, longitude=-3.7038)
    await _setup(hass, config_entry)
    await hass.config.async_update(latitude=41.0, longitude=-4.0)
    await hass.async_block_till_done()
    for name in SETTERS:
        getattr(mock_device, name).assert_not_called()


async def test_follows_ha_location(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await hass.config.async_update(
        latitude=40.4168, longitude=-3.7038, location_name="Casa"
    )
    await _setup(hass, _following(config_entry))
    mock_device.set_location.assert_called_once_with("Casa", 40.4168, -3.7038)

    mock_device.set_location.reset_mock()
    await hass.config.async_update(latitude=41.0, longitude=-4.0)
    await hass.async_block_till_done()
    mock_device.set_location.assert_called_once_with("Casa", 41.0, -4.0)


async def test_location_already_matches(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await hass.config.async_update(latitude=42.6, longitude=-5.5)
    await _setup(hass, _following(config_entry))
    mock_device.set_location.assert_not_called()


async def test_location_sync_disabled(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    await hass.config.async_update(latitude=40.4168, longitude=-3.7038)
    await _setup(hass, _following(config_entry, follow=False))
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


@pytest.mark.parametrize("target", ["area_id", "floor_id", "label_id"])
async def test_set_location_by_area_floor_or_label(
    hass: HomeAssistant,
    mock_device: MagicMock,
    config_entry: MockConfigEntry,
    target: str,
) -> None:
    """The action's target picker offers areas, floors and labels: all must work.

    Only the mirror in the area, on the floor or with the label is written to.
    """
    await _setup(hass, config_entry)
    await _setup(hass, _second_mirror())

    floor = fr.async_get(hass).async_create("Upstairs")
    area = ar.async_get(hass).async_create("Bathroom", floor_id=floor.floor_id)
    label = lr.async_get(hass).async_create("Mirrors")
    dr.async_get(hass).async_update_device(
        _device(hass, config_entry).id, area_id=area.id, labels={label.label_id}
    )
    ids = {"area_id": area.id, "floor_id": floor.floor_id, "label_id": label.label_id}

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_LOCATION,
        {target: ids[target], "name": "Madrid", "latitude": 40.4, "longitude": -3.7},
        blocking=True,
    )
    mock_device.set_location.assert_called_once_with("Madrid", 40.4, -3.7)


@pytest.mark.skipif(
    "exclude" not in cv.TARGET_SERVICE_FIELDS,
    reason="Home Assistant has had exclude in targets since 2026.11",
)
async def test_set_location_with_an_exclusion(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    """Both mirrors are in the area, and the target excludes one of them."""
    other = _second_mirror()
    await _setup(hass, config_entry)
    await _setup(hass, other)

    area = ar.async_get(hass).async_create("Bathroom")
    for entry in (config_entry, other):
        dr.async_get(hass).async_update_device(_device(hass, entry).id, area_id=area.id)

    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_LOCATION,
        {
            "area_id": area.id,
            "exclude": {"device_id": _device(hass, other).id},
            "name": "Madrid",
            "latitude": 40.4,
            "longitude": -3.7,
        },
        blocking=True,
    )
    mock_device.set_location.assert_called_once_with("Madrid", 40.4, -3.7)

    # Without the exclusion, both are written to.
    mock_device.set_location.reset_mock()
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_LOCATION,
        {"area_id": area.id, "name": "Madrid", "latitude": 40.4, "longitude": -3.7},
        blocking=True,
    )
    assert mock_device.set_location.call_count == 2


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


async def test_a_network_error_also_looks_for_the_mirror(
    hass: HomeAssistant,
    mock_device: MagicMock,
    config_entry: MockConfigEntry,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Not only ConnectionError: any socket error is a failed poll."""
    await _setup(hass, config_entry)
    mock_device.poll.side_effect = OSError(101, "Network is unreachable")
    mock_device.discover.return_value = []
    freezer.tick(61)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_device.discover.assert_called_once()
    assert not config_entry.runtime_data.last_update_success
    assert (
        hass.states.get("binary_sensor.wisemirror_2m09_ceb8_connectivity").state
        == "off"
    )


async def test_a_mirror_keyed_by_its_ip_is_not_looked_for(
    hass: HomeAssistant,
    mock_device: MagicMock,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Without a MAC there is nothing to recognise it by in a scan."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="WiseMirror (192.168.1.50)",
        unique_id="192.168.1.50",
        data={CONF_HOST: "192.168.1.50", CONF_BSSID: "192.168.1.50"},
    )
    await _setup(hass, entry)
    mock_device.poll.side_effect = ConnectionError("gone")
    freezer.tick(61)
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)

    mock_device.discover.assert_not_called()
    assert not entry.runtime_data.last_update_success


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


async def test_firmware_update_reaches_the_device(
    hass: HomeAssistant,
    mock_device: MagicMock,
    config_entry: MockConfigEntry,
    state: dict[str, Any],
) -> None:
    await _setup(hass, config_entry)
    assert _device(hass, config_entry).sw_version == "V1.9.250215"
    state["version"] = "V2.0.260101"
    await config_entry.runtime_data.async_refresh()
    assert _device(hass, config_entry).sw_version == "V2.0.260101"


async def test_an_unchanged_poll_updates_no_entity(
    hass: HomeAssistant,
    mock_device: MagicMock,
    config_entry: MockConfigEntry,
    state: dict[str, Any],
) -> None:
    await _setup(hass, config_entry)
    coordinator = config_entry.runtime_data
    updates: list[None] = []
    unsub = coordinator.async_add_listener(lambda: updates.append(None))
    await coordinator.async_refresh()
    assert updates == []
    state["brightness"] = 50
    await coordinator.async_refresh()
    assert len(updates) == 1
    unsub()
