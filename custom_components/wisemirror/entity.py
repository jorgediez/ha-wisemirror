"""Base entity for WiseMirror."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_MODEL, DOMAIN, MANUFACTURER
from .coordinator import WiseMirrorCoordinator


class WiseMirrorEntity(CoordinatorEntity[WiseMirrorCoordinator]):
    """Common base: device grouping + availability."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: WiseMirrorCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        data = coordinator.data or {}
        # The config entry's unique id is the mirror's MAC ("bssid" in the protocol),
        # or its IP if the MAC could not be read when it was added.
        ident = entry.unique_id or coordinator.device.host
        self._attr_unique_id = f"{ident}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, ident)},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=data.get("model") or entry.data.get(CONF_MODEL),
            sw_version=data.get("version"),
            connections={(CONNECTION_NETWORK_MAC, ident)} if ":" in ident else set(),
        )

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.data)

    @property
    def _data(self) -> dict[str, Any]:
        return self.coordinator.data or {}
