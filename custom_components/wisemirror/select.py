"""WiseMirror multi-choice settings (temperature unit, weather server)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WiseMirrorConfigEntry, WiseMirrorCoordinator
from .entity import WiseMirrorEntity
from .protocol import SERVER_TO_RAW

PARALLEL_UPDATES = 0  # writes are serialized by the coordinator

UNIT_CELSIUS = "celsius"
UNIT_FAHRENHEIT = "fahrenheit"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WiseMirrorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [TemperatureUnitSelect(coordinator), WeatherServerSelect(coordinator)]
    )


class TemperatureUnitSelect(WiseMirrorEntity, SelectEntity):
    """Unit the mirror displays temperatures in."""

    _attr_translation_key = "temperature_unit"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = [UNIT_CELSIUS, UNIT_FAHRENHEIT]

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        super().__init__(coordinator, "temperature_unit")

    @property
    def current_option(self) -> str | None:
        unit = self._data.get("unit")
        if unit is None:
            return None
        return UNIT_CELSIUS if unit == 1 else UNIT_FAHRENHEIT

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_send(
            self.coordinator.device.set_unit_celsius, option == UNIT_CELSIUS
        )


class WeatherServerSelect(WiseMirrorEntity, SelectEntity):
    """Weather data source the mirror uses (app labels Auto, No1..No5)."""

    _attr_translation_key = "weather_server"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_options = list(SERVER_TO_RAW)

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        super().__init__(coordinator, "weather_server")

    @property
    def current_option(self) -> str | None:
        return self._data.get("server")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_set_weather(server_raw=SERVER_TO_RAW[option])
