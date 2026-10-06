"""Integration-wide (not per-mirror) configuration: the poll interval.

Stored in a single HA Store shared by all mirror config entries, and cached in
hass.data so every coordinator reads the same value.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import (
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL_SECONDS,
    GLOBAL_DATA_KEY,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .coordinator import async_loaded_coordinators


async def async_get_scan_interval(hass: HomeAssistant) -> int:
    """Return the integration-wide poll interval in seconds (loads + caches)."""
    cache = hass.data.get(GLOBAL_DATA_KEY)
    if cache is None:
        store: Store[dict[str, int]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        saved = await store.async_load() or {}
        cache = {
            "store": store,
            CONF_SCAN_INTERVAL: saved.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_SECONDS),
        }
        hass.data[GLOBAL_DATA_KEY] = cache
    return cache[CONF_SCAN_INTERVAL]


async def async_set_scan_interval(hass: HomeAssistant, seconds: int) -> None:
    """Persist a new poll interval and apply it to every loaded mirror."""
    await async_get_scan_interval(hass)  # ensure loaded
    cache = hass.data[GLOBAL_DATA_KEY]
    if cache[CONF_SCAN_INTERVAL] == seconds:
        return
    cache[CONF_SCAN_INTERVAL] = seconds
    await cache["store"].async_save({CONF_SCAN_INTERVAL: seconds})
    for coordinator in async_loaded_coordinators(hass):
        coordinator.update_interval = timedelta(seconds=seconds)
        await coordinator.async_request_refresh()


async def async_remove_global_config(hass: HomeAssistant) -> None:
    """Delete the stored global settings (when the last mirror is removed)."""
    await async_get_scan_interval(hass)
    cache = hass.data.pop(GLOBAL_DATA_KEY)
    await cache["store"].async_remove()
