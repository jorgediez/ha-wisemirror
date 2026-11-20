"""Tests for finding mirrors on Home Assistant's networks."""

from __future__ import annotations

from ipaddress import IPv4Address
from unittest.mock import AsyncMock, patch

from custom_components.wisemirror.discovery import async_discover_mirrors
from homeassistant.core import HomeAssistant


async def test_probes_each_enabled_interface(hass: HomeAssistant) -> None:
    """Each interface's broadcast address, as Home Assistant's network lists them."""
    addresses = {IPv4Address("255.255.255.255"), IPv4Address("192.168.1.255")}
    with (
        patch(
            "homeassistant.components.network.async_get_ipv4_broadcast_addresses",
            AsyncMock(return_value=addresses),
        ),
        patch(
            "custom_components.wisemirror.discovery.discover",
            AsyncMock(return_value=[{"bssid": "30:30:f9:f3:ce:b8"}]),
        ) as discover,
    ):
        found = await async_discover_mirrors(hass)
    discover.assert_awaited_once_with(["192.168.1.255", "255.255.255.255"])
    assert found == [{"bssid": "30:30:f9:f3:ce:b8"}]
