"""WiseMirror connectivity (availability) sensor."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WiseMirrorConfigEntry, WiseMirrorCoordinator
from .entity import WiseMirrorEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WiseMirrorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([MirrorConnectivity(entry.runtime_data)])


class MirrorConnectivity(WiseMirrorEntity, BinarySensorEntity):
    """Reports whether the mirror is reachable.

    Unlike the other entities (which go 'unavailable' when polling fails), this
    one stays available so it can explicitly report online/offline for automations.
    """

    _attr_translation_key = "connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        super().__init__(coordinator, "connectivity")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self.coordinator.last_update_success
