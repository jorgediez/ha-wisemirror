"""Diagnostics support for WiseMirror."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_BSSID, CONF_HOST
from .coordinator import WiseMirrorConfigEntry
from .global_config import async_get_scan_interval

TO_REDACT = {
    CONF_BSSID,
    CONF_HOST,
    "location",
    "location_lat",
    "location_lon",
    "unique_id",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: WiseMirrorConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
                "options": dict(entry.options),
            },
            TO_REDACT,
        ),
        "scan_interval": await async_get_scan_interval(hass),
        "last_update_success": coordinator.last_update_success,
        "state": async_redact_data(coordinator.data or {}, TO_REDACT),
    }
