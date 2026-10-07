"""Tests for diagnostics."""

from __future__ import annotations

from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wisemirror.diagnostics import (
    async_get_config_entry_diagnostics,
)
from homeassistant.core import HomeAssistant


async def test_diagnostics_redacts(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, config_entry)
    assert diag["scan_interval"] == 60
    assert diag["last_update_success"] is True
    assert diag["entry"]["unique_id"] == "**REDACTED**"
    assert diag["entry"]["data"]["host"] == "**REDACTED**"
    assert diag["entry"]["data"]["bssid"] == "**REDACTED**"
    assert diag["state"]["location_lat"] == "**REDACTED**"
    assert diag["state"]["location"] == "**REDACTED**"
    assert diag["state"]["model"] == "2M09"
    assert diag["state"]["brightness"] == 80
