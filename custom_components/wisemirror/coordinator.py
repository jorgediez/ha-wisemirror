"""DataUpdateCoordinator for a single WiseMirror device."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_HOST, DOMAIN
from .discovery import async_discover_mirrors
from .protocol import WiseMirrorDevice

_LOGGER = logging.getLogger(__name__)

type WiseMirrorConfigEntry = ConfigEntry[WiseMirrorCoordinator]
# A device write: the WiseMirrorDevice method and its arguments.
type _Write = tuple[Callable[..., Awaitable[bool]], tuple[Any, ...]]


class WiseMirrorCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Polls one mirror and exposes its state; recovers IP changes via bssid."""

    config_entry: WiseMirrorConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: WiseMirrorConfigEntry,
        device: WiseMirrorDevice,
        scan_interval_seconds: int,
    ) -> None:
        """Create the coordinator for one mirror."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {device.host}",
            update_interval=timedelta(seconds=scan_interval_seconds),
            # Most polls find nothing changed: don't write every entity's state.
            always_update=False,
        )
        self.device = device
        # Some commands (weather, night window) carry settings besides the one
        # changed, taken from the current state: one write at a time, each
        # built from the state its predecessor left.
        self._write_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self._async_poll()
        self._async_update_device(data)
        return data

    async def _async_poll(self) -> dict[str, Any]:
        try:
            return await self.device.poll()
        except OSError as err:
            # The mirror may have a new IP (DHCP): look for it by its MAC. Not for
            # a mirror added before its MAC could be read, which is keyed by its IP.
            if self.device.bssid and ":" in self.device.bssid:
                relocated = await self._async_relocate(self.device.bssid)
                if relocated and relocated != self.device.host:
                    _LOGGER.info(
                        "WiseMirror %s moved from %s to %s",
                        self.device.bssid,
                        self.device.host,
                        relocated,
                    )
                    self.device.host = relocated
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, CONF_HOST: relocated},
                    )
                    try:
                        return await self.device.poll()
                    except OSError:
                        pass
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="update_failed",
                translation_placeholders={"host": self.device.host, "error": str(err)},
            ) from err

    async def _async_relocate(self, bssid: str) -> str | None:
        for m in await async_discover_mirrors(self.hass):
            if m.get("bssid") == bssid:
                return m.get("address")
        return None

    def _async_update_device(self, data: dict[str, Any]) -> None:
        """Keep the device's firmware and model as the mirror reports them."""
        identifier = (DOMAIN, self.config_entry.unique_id or self.device.host)
        registry = dr.async_get(self.hass)
        # Search this entry's own devices: async_get_device is deprecated from
        # 2026.11, and its replacements don't exist in older releases.
        device = next(
            (
                device
                for device in dr.async_entries_for_config_entry(
                    registry, self.config_entry.entry_id
                )
                if identifier in device.identifiers
            ),
            None,
        )
        if device is None:  # not created yet: the entities will create it
            return
        changes = {
            attr: data[key]
            for attr, key in (("sw_version", "version"), ("model", "model"))
            if data.get(key) and data[key] != getattr(device, attr)
        }
        if changes:
            registry.async_update_device(device.id, **changes)

    async def async_send(
        self, func: Callable[..., Awaitable[bool]], *args: Any
    ) -> None:
        """Run a device write, then refresh state.

        Raises HomeAssistantError if the mirror did not acknowledge the command.
        """
        await self._async_write(lambda: (func, args))

    async def async_set_weather(
        self, two_day: bool | None = None, server_raw: int | None = None
    ) -> None:
        """Change one half of the weather command, keeping the other half as is."""

        def _build() -> _Write | None:
            data = self.data or {}
            day = data.get("two_day") if two_day is None else two_day
            server = data.get("server_raw") if server_raw is None else server_raw
            if day is None or server is None:
                return None
            return self.device.set_weather, (bool(day), server)

        await self._async_write(_build)

    async def async_set_night_time(
        self,
        start: tuple[int, int] | None = None,
        end: tuple[int, int] | None = None,
    ) -> None:
        """Change the night-mode start or end time, keeping the other one as is."""

        def _build() -> _Write | None:
            data = self.data or {}
            s = start or data.get("night_start")
            e = end or data.get("night_end")
            if s is None or e is None:
                return None
            return self.device.set_night_time, (s[0], s[1], e[0], e[1])

        await self._async_write(_build)

    async def _async_write(self, build: Callable[[], _Write | None]) -> None:
        """Build a write from the latest state, send it, then refresh.

        A builder returns None when part of the command is a setting the last
        poll didn't return (one of its replies was lost). That setting is read
        again rather than guessed: a default would overwrite it on the mirror.
        """
        async with self._write_lock:
            write = build()  # built under the lock, from the latest state
            if write is None:
                await self.async_refresh()
                write = build()
            if write is None:
                raise HomeAssistantError(
                    translation_domain=DOMAIN,
                    translation_key="current_state_unknown",
                    translation_placeholders={"host": self.device.host},
                )
            func, args = write
            ok = await func(*args)
            await self.async_refresh()
        if not ok:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="command_not_acknowledged",
                translation_placeholders={"host": self.device.host},
            )


def async_loaded_coordinators(hass: HomeAssistant) -> list[WiseMirrorCoordinator]:
    """Return the coordinators of all loaded mirrors."""
    return [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if entry.state is ConfigEntryState.LOADED
    ]
