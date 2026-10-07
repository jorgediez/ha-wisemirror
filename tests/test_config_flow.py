"""Tests for the WiseMirror config and options flows."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wisemirror.const import (
    CONF_BSSID,
    CONF_HOST,
    CONF_MODEL,
    CONF_SCAN_INTERVAL,
    CONF_USE_HA_LOCATION,
    DOMAIN,
)
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import BSSID, HOST, MODEL


async def test_user_picks_discovered_mirror(
    hass: HomeAssistant, mock_device: MagicMock
) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": BSSID}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "WiseMirror 2M09 (CEB8)"
    assert result["data"] == {CONF_HOST: HOST, CONF_BSSID: BSSID, CONF_MODEL: MODEL}
    assert result["result"].unique_id == BSSID


async def test_user_chooses_manual(hass: HomeAssistant, mock_device: MagicMock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"device": "manual"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"


async def test_manual_when_nothing_discovered(
    hass: HomeAssistant, mock_device: MagicMock
) -> None:
    mock_device.discover.return_value = []
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "manual"

    mock_device.poll.side_effect = ConnectionError
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: " 192.168.1.50 "}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}

    mock_device.poll.side_effect = None
    mock_device.poll.return_value = {"bssid": BSSID, "model": MODEL}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: " 192.168.1.50 "}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_HOST] == "192.168.1.50"
    assert result["result"].unique_id == BSSID


async def test_manual_already_configured_updates_host(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    # the configured mirror is filtered out of discovery -> straight to manual
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["step_id"] == "manual"

    mock_device.poll.side_effect = None
    mock_device.poll.return_value = {"bssid": BSSID, "model": MODEL}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: "192.168.1.99"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data[CONF_HOST] == "192.168.1.99"


async def test_options_flow(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data
    assert coordinator.update_interval == timedelta(seconds=60)

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 30, CONF_USE_HA_LOCATION: False},
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert config_entry.options == {CONF_USE_HA_LOCATION: False}

    # options changed -> entry reloaded with a new coordinator using the new interval
    assert config_entry.runtime_data is not coordinator
    assert config_entry.runtime_data.update_interval == timedelta(seconds=30)


async def test_options_interval_only_applies_live(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data

    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_SCAN_INTERVAL: 120, CONF_USE_HA_LOCATION: True},
    )
    await hass.async_block_till_done()
    # no reload needed: same coordinator, interval updated in place
    assert config_entry.runtime_data is coordinator
    assert coordinator.update_interval == timedelta(seconds=120)


async def _reconfigure(hass: HomeAssistant, entry: MockConfigEntry, host: str) -> dict:
    """Run the reconfigure flow for an entry, entering a new address."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_HOST: host}
    )
    await hass.async_block_till_done()
    return result


async def test_reconfigure_changes_the_address(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await _reconfigure(hass, config_entry, " 192.168.1.99 ")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert config_entry.data[CONF_HOST] == "192.168.1.99"
    assert config_entry.state is ConfigEntryState.LOADED
    assert config_entry.runtime_data.device.host == "192.168.1.99"


async def test_reconfigure_retries_an_unreachable_address(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    mock_device.poll.side_effect = ConnectionError

    result = await _reconfigure(hass, config_entry, "192.168.1.99")

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert config_entry.data[CONF_HOST] == HOST


async def test_reconfigure_refuses_a_different_mirror(
    hass: HomeAssistant, mock_device: MagicMock, config_entry: MockConfigEntry
) -> None:
    config_entry.add_to_hass(hass)
    mock_device.poll.side_effect = None
    mock_device.poll.return_value = {"bssid": "aa:bb:cc:dd:ee:ff", "model": MODEL}

    result = await _reconfigure(hass, config_entry, "192.168.1.99")

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_device"
    assert config_entry.data[CONF_HOST] == HOST


async def test_reconfigure_a_mirror_keyed_by_its_ip(
    hass: HomeAssistant, mock_device: MagicMock
) -> None:
    """Added before its MAC could be read, it has nothing to compare against."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=HOST,
        data={CONF_HOST: HOST, CONF_BSSID: HOST, CONF_MODEL: MODEL},
    )
    entry.add_to_hass(hass)
    mock_device.poll.side_effect = None
    mock_device.poll.return_value = {"bssid": "aa:bb:cc:dd:ee:ff", "model": MODEL}

    result = await _reconfigure(hass, entry, "192.168.1.99")

    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.1.99"
