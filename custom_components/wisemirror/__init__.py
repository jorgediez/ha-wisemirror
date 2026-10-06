"""The WiseMirror (Alasta / BYECOLD / ... smart mirror) integration."""

from __future__ import annotations

import logging

from homeassistant.const import EVENT_CORE_CONFIG_UPDATE, Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    ATTR_LATITUDE,
    ATTR_LOCATION_NAME,
    ATTR_LONGITUDE,
    CONF_BSSID,
    CONF_HOST,
    CONF_USE_HA_LOCATION,
    DEFAULT_USE_HA_LOCATION,
    DOMAIN,
    SERVICE_SET_LOCATION,
)
from .coordinator import (
    WiseMirrorConfigEntry,
    WiseMirrorCoordinator,
    async_loaded_coordinators,
)
from .global_config import async_get_scan_interval, async_remove_global_config
from .protocol import WiseMirrorDevice

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SET_LOCATION_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("entity_id"): cv.entity_ids,
        vol.Optional("area_id"): vol.All(cv.ensure_list, [cv.string]),
        vol.Required(ATTR_LOCATION_NAME): cv.string,
        vol.Required(ATTR_LATITUDE): vol.All(vol.Coerce(float), vol.Range(min=-90, max=90)),
        vol.Required(ATTR_LONGITUDE): vol.All(vol.Coerce(float), vol.Range(min=-180, max=180)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""

    async def _handle_set_location(call: ServiceCall) -> None:
        entry_ids = _config_entry_ids_for_targets(hass, call)
        coordinators = [
            coordinator
            for coordinator in async_loaded_coordinators(hass)
            if coordinator.config_entry.entry_id in entry_ids
        ]
        if not coordinators:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="no_target_mirror"
            )
        for coordinator in coordinators:
            await coordinator.async_send(
                coordinator.device.set_location,
                call.data[ATTR_LOCATION_NAME],
                call.data[ATTR_LATITUDE],
                call.data[ATTR_LONGITUDE],
            )

    hass.services.async_register(
        DOMAIN, SERVICE_SET_LOCATION, _handle_set_location, schema=SET_LOCATION_SCHEMA
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: WiseMirrorConfigEntry) -> bool:
    """Set up WiseMirror from a config entry."""
    device = WiseMirrorDevice(host=entry.data[CONF_HOST], bssid=entry.data.get(CONF_BSSID))
    scan_interval = await async_get_scan_interval(hass)
    coordinator = WiseMirrorCoordinator(hass, entry, device, scan_interval)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload when the per-mirror options change (not on data-only updates such as
    # the host being rewritten after an IP change).
    applied_options = dict(entry.options)

    async def _async_entry_updated(hass: HomeAssistant, entry: WiseMirrorConfigEntry) -> None:
        if dict(entry.options) != applied_options:
            await hass.config_entries.async_reload(entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    # Follow Home Assistant's home location, if enabled.
    if entry.options.get(CONF_USE_HA_LOCATION, DEFAULT_USE_HA_LOCATION):
        await _async_sync_ha_location(hass, coordinator)

        async def _on_core_config(_event: Event) -> None:
            await _async_sync_ha_location(hass, coordinator)

        entry.async_on_unload(hass.bus.async_listen(EVENT_CORE_CONFIG_UPDATE, _on_core_config))

    return True


async def _async_sync_ha_location(hass: HomeAssistant, coordinator: WiseMirrorCoordinator) -> None:
    """Push HA's home lat/lon to the mirror if it differs from the stored one."""
    lat = hass.config.latitude
    lon = hass.config.longitude
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return  # HA location not configured; leave the mirror alone
    name = hass.config.location_name or "Home"
    data = coordinator.data or {}
    cur_lat, cur_lon = data.get("location_lat"), data.get("location_lon")
    if (
        cur_lat is not None
        and cur_lon is not None
        and round(cur_lat, 4) == round(lat, 4)
        and round(cur_lon, 4) == round(lon, 4)
    ):
        return  # already matches
    try:
        await coordinator.async_send(coordinator.device.set_location, name, lat, lon)
    except HomeAssistantError as err:
        _LOGGER.warning("Could not sync Home Assistant's location to the mirror: %s", err)


async def async_unload_entry(hass: HomeAssistant, entry: WiseMirrorConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: WiseMirrorConfigEntry) -> None:
    """Drop the shared global settings once the last mirror is removed."""
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    if not remaining:
        await async_remove_global_config(hass)


def _config_entry_ids_for_targets(hass: HomeAssistant, call: ServiceCall) -> set[str]:
    """Resolve device/entity/area targets to config entry ids."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    device_ids: set[str] = set(call.data.get("device_id", []))

    for entity_id in call.data.get("entity_id", []):
        if (ent := ent_reg.async_get(entity_id)) and ent.device_id:
            device_ids.add(ent.device_id)

    for area_id in call.data.get("area_id", []):
        device_ids.update(d.id for d in dr.async_entries_for_area(dev_reg, area_id))

    entry_ids: set[str] = set()
    for device_id in device_ids:
        if device := dev_reg.async_get(device_id):
            entry_ids.update(device.config_entries)
    return entry_ids
