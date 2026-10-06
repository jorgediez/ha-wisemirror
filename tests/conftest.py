"""Shared fixtures for the WiseMirror tests."""

from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.wisemirror.const import (
    CONF_BSSID,
    CONF_HOST,
    CONF_MODEL,
    DOMAIN,
)
from custom_components.wisemirror.protocol import WiseMirrorDevice

HOST = "192.168.1.244"
BSSID = "30:30:f9:f3:ce:b8"
MODEL = "2M09"

# What WiseMirrorDevice.poll() returns for a healthy 2M09.
STATE: dict[str, Any] = {
    "available": True,
    "host": HOST,
    "bssid": BSSID,
    "model": MODEL,
    "version": "V1.9.250215",
    "has_humidity_sensor": True,
    "humidity": 45,
    "key_tone": False,
    "hour_24": True,
    "day_month": True,
    "unit": 1,
    "brightness": 80,
    "night_on": False,
    "night_start": (22, 30),
    "night_end": (7, 0),
    "night_light": 10,
    "location": "León",
    "location_lat": 42.6,
    "location_lon": -5.5,
    "temperature_c": 25.0,
    "two_day": False,
    "today_weather": 0,
    "server": "auto",
    "server_raw": 255,
}

DISCOVERED = {
    "model": MODEL,
    "bssid": BSSID,
    "address": HOST,
    "humidity": 45,
    "temp": 25,
    "unit": 1,
    "version": "V1.9.250215",
}

SETTERS = (
    "set_brightness",
    "set_night_brightness",
    "set_hour24",
    "set_daymonth",
    "set_key_tone",
    "set_unit_celsius",
    "set_night_mode",
    "set_night_time",
    "set_weather",
    "set_location",
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom_components/ in every test."""


@pytest.fixture
def state() -> dict[str, Any]:
    """Mutable copy of the mirror state returned by poll()."""
    return deepcopy(STATE)


@pytest.fixture
def mock_device(state: dict[str, Any]) -> Generator[MagicMock]:
    """Patch every WiseMirrorDevice call that would touch the network.

    Yields a namespace whose attributes are the mocks (poll, set_*, discover).
    """
    mocks = MagicMock()
    mocks.poll.side_effect = lambda: deepcopy(state)
    patches = [patch.object(WiseMirrorDevice, "poll", mocks.poll)]
    for name in SETTERS:
        getattr(mocks, name).return_value = True
        patches.append(patch.object(WiseMirrorDevice, name, getattr(mocks, name)))
    mocks.discover.return_value = [dict(DISCOVERED)]
    patches.append(patch("custom_components.wisemirror.config_flow.discover", mocks.discover))
    patches.append(patch("custom_components.wisemirror.coordinator.discover", mocks.discover))
    for p in patches:
        p.start()
    yield mocks
    for p in patches:
        p.stop()


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """A config entry for the test mirror."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"WiseMirror {MODEL} (CEB8)",
        unique_id=BSSID,
        data={CONF_HOST: HOST, CONF_BSSID: BSSID, CONF_MODEL: MODEL},
    )
