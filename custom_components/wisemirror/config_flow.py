"""Config flow for WiseMirror: scan the LAN or add by IP."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
)

from .const import (
    CONF_BSSID,
    CONF_HOST,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    CONF_USE_HA_LOCATION,
    DEFAULT_USE_HA_LOCATION,
    DOMAIN,
    MAX_SCAN_INTERVAL_SECONDS,
    MIN_SCAN_INTERVAL_SECONDS,
)
from .global_config import async_get_scan_interval, async_set_scan_interval
from .protocol import WiseMirrorDevice, discover

CONF_DEVICE = "device"
MANUAL = "manual"


def _title(model: str | None, bssid: str | None, host: str) -> str:
    """'WiseMirror 2M09 (CEB8)' — the MAC suffix tells several mirrors apart."""
    suffix = bssid.replace(":", "")[-4:].upper() if bssid and ":" in bssid else host
    return f"WiseMirror {model} ({suffix})" if model else f"WiseMirror ({suffix})"


class WiseMirrorConfigFlow(ConfigFlow, domain=DOMAIN):
    """Discover mirrors via UDP broadcast, or let the user type an IP."""

    VERSION = 1

    def __init__(self) -> None:
        """Start with no mirrors discovered."""
        self._discovered: dict[str, dict[str, Any]] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return WiseMirrorOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer the mirrors found on the LAN, or manual entry."""
        if user_input is not None:
            choice = user_input[CONF_DEVICE]
            if choice == MANUAL:
                return await self.async_step_manual()
            info = self._discovered[choice]
            await self.async_set_unique_id(info["bssid"])
            self._abort_if_unique_id_configured(updates={CONF_HOST: info["address"]})
            return self.async_create_entry(
                title=_title(info.get("model"), info["bssid"], info["address"]),
                data={
                    CONF_HOST: info["address"],
                    CONF_BSSID: info["bssid"],
                    CONF_MODEL: info.get("model"),
                },
            )

        found = await self.hass.async_add_executor_job(discover)
        configured = self._async_current_ids()
        self._discovered = {
            m["bssid"]: m
            for m in found
            if m.get("bssid") and m["bssid"] not in configured
        }
        if not self._discovered:
            return await self.async_step_manual()

        options = [
            SelectOptionDict(
                value=bssid, label=f"{m.get('model') or 'WiseMirror'} @ {m['address']}"
            )
            for bssid, m in self._discovered.items()
        ]
        options.append(SelectOptionDict(value=MANUAL, label=MANUAL))
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE): SelectSelector(
                        SelectSelectorConfig(
                            options=options, translation_key=CONF_DEVICE
                        )
                    )
                }
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a mirror by its IP address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            device = WiseMirrorDevice(host=host)
            try:
                state = await self.hass.async_add_executor_job(device.poll)
            except ConnectionError:
                errors["base"] = "cannot_connect"
            else:
                bssid = state.get("bssid") or host
                await self.async_set_unique_id(bssid)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=_title(state.get("model"), bssid, host),
                    data={
                        CONF_HOST: host,
                        CONF_BSSID: bssid,
                        CONF_MODEL: state.get("model"),
                    },
                )

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )


class WiseMirrorOptionsFlow(OptionsFlow):
    """Options: poll interval (integration-wide) + follow HA's home location (per mirror)."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Set the poll interval and whether to follow HA's location."""
        if user_input is not None:
            # Poll interval is integration-wide: persisted globally, applied to all mirrors.
            await async_set_scan_interval(
                self.hass, int(user_input[CONF_SCAN_INTERVAL])
            )
            return self.async_create_entry(
                data={CONF_USE_HA_LOCATION: user_input[CONF_USE_HA_LOCATION]},
            )

        current_loc = self.config_entry.options.get(
            CONF_USE_HA_LOCATION, DEFAULT_USE_HA_LOCATION
        )
        current_interval = await async_get_scan_interval(self.hass)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL, default=current_interval
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL_SECONDS,
                            max=MAX_SCAN_INTERVAL_SECONDS,
                            step=5,
                            unit_of_measurement="s",
                            mode=NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Required(CONF_USE_HA_LOCATION, default=current_loc): bool,
                }
            ),
        )
