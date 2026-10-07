"""WiseMirror brightness controls."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
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
    """Set up the brightness numbers."""
    coordinator = entry.runtime_data
    async_add_entities(
        [DayBrightnessNumber(coordinator), NightBrightnessNumber(coordinator)]
    )


class _BaseBrightness(WiseMirrorEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER


class DayBrightnessNumber(_BaseBrightness):
    """Display brightness outside night mode."""

    _attr_translation_key = "brightness"

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        """Create the number for a mirror."""
        super().__init__(coordinator, "brightness")

    @property
    def native_value(self) -> int | None:
        """Return the brightness, in percent."""
        return self._data.get("brightness")

    async def async_set_native_value(self, value: float) -> None:
        """Send a new brightness to the mirror."""
        await self.coordinator.async_send(
            self.coordinator.device.set_brightness, int(value)
        )


class NightBrightnessNumber(_BaseBrightness):
    """Display brightness during night mode."""

    _attr_translation_key = "night_brightness"

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        """Create the number for a mirror."""
        super().__init__(coordinator, "night_brightness")

    @property
    def native_value(self) -> int | None:
        """Return the night brightness, in percent."""
        return self._data.get("night_light")

    async def async_set_native_value(self, value: float) -> None:
        """Send a new night brightness to the mirror."""
        await self.coordinator.async_send(
            self.coordinator.device.set_night_brightness, int(value)
        )
