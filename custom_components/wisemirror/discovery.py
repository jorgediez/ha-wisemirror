"""Find mirrors on the networks Home Assistant is set to use."""

from __future__ import annotations

from homeassistant.components import network
from homeassistant.core import HomeAssistant

from .protocol import discover


async def async_discover_mirrors(hass: HomeAssistant) -> list[dict]:
    """Broadcast the probe on each enabled network interface.

    255.255.255.255 only leaves through one interface, the one with the default
    route; each interface's own broadcast address reaches its network. The
    interfaces are the ones enabled under Settings > System > Network.
    """
    addresses = await network.async_get_ipv4_broadcast_addresses(hass)
    return await discover(sorted(str(address) for address in addresses))
