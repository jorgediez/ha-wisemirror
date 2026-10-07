"""WiseMirror on/off toggles."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import WiseMirrorConfigEntry, WiseMirrorCoordinator
from .entity import WiseMirrorEntity

PARALLEL_UPDATES = 0  # writes are serialized by the coordinator


@dataclass(frozen=True, kw_only=True)
class WiseMirrorSwitchDescription(SwitchEntityDescription):
    """Maps a switch to its state key and the device call that sets it."""

    state_key: str
    set_fn: Callable[[WiseMirrorCoordinator, bool], Awaitable[None]]


SWITCHES: tuple[WiseMirrorSwitchDescription, ...] = (
    WiseMirrorSwitchDescription(
        key="night_mode",
        translation_key="night_mode",
        state_key="night_on",
        set_fn=lambda c, on: c.async_send(c.device.set_night_mode, on),
    ),
    WiseMirrorSwitchDescription(
        key="two_day_weather",
        translation_key="two_day_weather",
        state_key="two_day",
        set_fn=lambda c, on: c.async_set_weather(two_day=on),
    ),
    WiseMirrorSwitchDescription(
        key="hour_24",
        translation_key="hour_24",
        state_key="hour_24",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda c, on: c.async_send(c.device.set_hour24, on),
    ),
    WiseMirrorSwitchDescription(
        key="day_month",
        translation_key="day_month",
        state_key="day_month",
        entity_category=EntityCategory.CONFIG,
        set_fn=lambda c, on: c.async_send(c.device.set_daymonth, on),
    ),
    WiseMirrorSwitchDescription(
        key="key_tone",
        translation_key="key_tone",
        state_key="key_tone",
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,  # unsupported on some models
        set_fn=lambda c, on: c.async_send(c.device.set_key_tone, on),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WiseMirrorConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches."""
    coordinator = entry.runtime_data
    async_add_entities(WiseMirrorSwitch(coordinator, desc) for desc in SWITCHES)


class WiseMirrorSwitch(WiseMirrorEntity, SwitchEntity):
    """An on/off setting of the mirror."""

    entity_description: WiseMirrorSwitchDescription

    def __init__(
        self,
        coordinator: WiseMirrorCoordinator,
        description: WiseMirrorSwitchDescription,
    ) -> None:
        """Create the switch for a mirror from its description."""
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        """Return whether the setting is on."""
        return self._data.get(self.entity_description.state_key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the setting on."""
        await self.entity_description.set_fn(self.coordinator, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the setting off."""
        await self.entity_description.set_fn(self.coordinator, False)
