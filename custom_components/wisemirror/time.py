"""WiseMirror night-mode start/end times."""

from __future__ import annotations

from datetime import time as dt_time

from homeassistant.components.time import TimeEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WiseMirrorConfigEntry, WiseMirrorCoordinator
from .entity import WiseMirrorEntity

PARALLEL_UPDATES = 0  # writes are serialized by the coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WiseMirrorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the night-mode start and end times."""
    coordinator = entry.runtime_data
    async_add_entities(
        [NightTime(coordinator, "night_start"), NightTime(coordinator, "night_end")]
    )


class NightTime(WiseMirrorEntity, TimeEntity):
    """Start ("night_start") or end ("night_end") of the mirror's night mode."""

    def __init__(self, coordinator: WiseMirrorCoordinator, key: str) -> None:
        """Create the time entity for the start or end key."""
        super().__init__(coordinator, key)
        self._key = key
        self._attr_translation_key = key

    @property
    def native_value(self) -> dt_time | None:
        """Return the configured time."""
        hm = self._data.get(self._key)
        if not hm:
            return None
        return dt_time(hour=int(hm[0]) % 24, minute=int(hm[1]) % 60)

    async def async_set_value(self, value: dt_time) -> None:
        """Send the new time, keeping the other end as it is."""
        hm = (value.hour, value.minute)
        if self._key == "night_start":
            await self.coordinator.async_set_night_time(start=hm)
        else:
            await self.coordinator.async_set_night_time(end=hm)
