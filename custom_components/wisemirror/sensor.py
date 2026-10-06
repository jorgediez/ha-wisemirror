"""WiseMirror sensors."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
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
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        IndoorTemperatureSensor(coordinator),
        LocationSensor(coordinator),
        IpSensor(coordinator),
    ]
    # Models without a humidity sensor report 0; only skip it when we know that.
    if coordinator.data.get("has_humidity_sensor", True):
        entities.append(HumiditySensor(coordinator))
    async_add_entities(entities)


class IndoorTemperatureSensor(WiseMirrorEntity, SensorEntity):
    _attr_translation_key = "indoor_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        super().__init__(coordinator, "indoor_temperature")

    @property
    def native_value(self) -> float | None:
        return self._data.get("temperature_c")


class HumiditySensor(WiseMirrorEntity, SensorEntity):
    _attr_translation_key = "humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        super().__init__(coordinator, "humidity")

    @property
    def native_value(self) -> int | None:
        return self._data.get("humidity")


class LocationSensor(WiseMirrorEntity, SensorEntity):
    _attr_translation_key = "location"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        super().__init__(coordinator, "location")

    @property
    def native_value(self) -> str | None:
        return self._data.get("location")


class IpSensor(WiseMirrorEntity, SensorEntity):
    _attr_translation_key = "ip_address"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        super().__init__(coordinator, "ip_address")

    @property
    def native_value(self) -> str | None:
        return self._data.get("host")
