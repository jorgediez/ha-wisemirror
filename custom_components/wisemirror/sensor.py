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
    """Set up the sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            IndoorTemperatureSensor(coordinator),
            HumiditySensor(coordinator),
            LocationSensor(coordinator),
            IpSensor(coordinator),
        ]
    )


class IndoorTemperatureSensor(WiseMirrorEntity, SensorEntity):
    """Temperature measured by the mirror."""

    _attr_translation_key = "indoor_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        """Create the sensor for a mirror."""
        super().__init__(coordinator, "indoor_temperature")

    @property
    def native_value(self) -> float | None:
        """Return the temperature, in Celsius."""
        return self._data.get("temperature_c")


class HumiditySensor(WiseMirrorEntity, SensorEntity):
    """Humidity measured by the mirror, on models that have a sensor."""

    _attr_translation_key = "humidity"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        """Create the sensor, disabled on models without one."""
        super().__init__(coordinator, "humidity")
        # Models without a humidity sensor report 0: disable the entity by default
        # there (users can still enable it). Only applies when first registered.
        self._attr_entity_registry_enabled_default = bool(
            coordinator.data.get("has_humidity_sensor", True)
        )

    @property
    def native_value(self) -> int | None:
        """Return the relative humidity, in percent."""
        return self._data.get("humidity")


class LocationSensor(WiseMirrorEntity, SensorEntity):
    """Name of the location the mirror shows weather for."""

    _attr_translation_key = "location"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        """Create the sensor for a mirror."""
        super().__init__(coordinator, "location")

    @property
    def native_value(self) -> str | None:
        """Return the location name."""
        return self._data.get("location")


class IpSensor(WiseMirrorEntity, SensorEntity):
    """IP address the mirror is reached at."""

    _attr_translation_key = "ip_address"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: WiseMirrorCoordinator) -> None:
        """Create the sensor for a mirror."""
        super().__init__(coordinator, "ip_address")

    @property
    def native_value(self) -> str | None:
        """Return the mirror's IP address."""
        return self._data.get("host")
