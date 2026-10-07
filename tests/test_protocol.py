"""Tests for the low-level protocol (no Home Assistant involved)."""

from __future__ import annotations

import socket
from unittest.mock import patch
import urllib.parse

import pytest

from custom_components.wisemirror import protocol
from custom_components.wisemirror.protocol import (
    WiseMirrorDevice,
    _build_frame,
    _decode_location,
    _parse_probe,
    discover,
)

PROBE_REPLY = b"I'm 2M09+25+1+V1.9.250215+30:30:f9:f3:ce:b8+192.168.1.244,0"


def _settings_ack(
    flags: int = 0b1110,
    brightness: int = 80,
    location: str = "Le%C3%B3n(42.6,-5.5)()",
) -> bytes:
    """A read-settings (0x10) reply laid out like the real mirror's."""
    b = bytearray(38)
    b[0], b[1], b[5] = 0xA5, 0x10, 1
    b[6], b[7] = flags, brightness
    b[30] = 1  # night mode on
    b[31:35] = bytes([22, 30, 7, 0])
    b[35] = 10  # night light
    loc = location.encode()
    b[36], b[37] = len(loc) >> 8, len(loc) & 0xFF
    return bytes(b) + loc + b"\x00\x5a"


def _weather_ack(flags: int = 1, server: int = 0) -> bytes:
    return bytes([0xA5, 0x16, 0, 4, 0, 1, flags, server, 0, 0, 0, 0x5A])


def _write_ack(opcode: int, ok: bool = True) -> bytes:
    return bytes([0xA5, opcode, 0, 0, 0, 1 if ok else 0, 0, 0x5A])


class FakeSocket:
    """Stands in for socket.socket; replies come from a shared queue."""

    replies: list[bytes | type[Exception]] = []
    sent: list[tuple[bytes, tuple[str, int]]] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def setsockopt(self, *args) -> None:
        pass

    def bind(self, addr) -> None:
        pass

    def settimeout(self, t) -> None:
        pass

    def sendto(self, data: bytes, addr) -> None:
        FakeSocket.sent.append((data, addr))

    def recvfrom(self, n: int):
        if not FakeSocket.replies:
            raise TimeoutError
        reply = FakeSocket.replies.pop(0)
        if isinstance(reply, type) and issubclass(reply, Exception):
            raise reply
        return reply, ("192.168.1.244", 8001)

    def close(self) -> None:
        pass


@pytest.fixture
def fake_socket():
    FakeSocket.replies = []
    FakeSocket.sent = []
    with patch.object(protocol.socket, "socket", FakeSocket):
        yield FakeSocket


def test_build_frame() -> None:
    # brightness 80: A5 06 00 01 00 01 50 chk 5A
    frame = _build_frame(0x06, bytes([80]))
    assert frame == bytes(
        [0xA5, 0x06, 0x00, 0x01, 0x00, 0x01, 80, 0x06 + 1 + 1 + 80, 0x5A]
    )


def test_parse_probe() -> None:
    parsed = _parse_probe(PROBE_REPLY.decode())
    assert parsed == {
        "model": "2M09",
        "bssid": "30:30:f9:f3:ce:b8",
        "address": "192.168.1.244",
        "humidity": 0,
        "temp": 25,
        "unit": 1,
        "version": "V1.9.250215",
    }


@pytest.mark.parametrize("reply", ["", "garbage", "I'm XXXX+1+2+3+aa:bb+1.2.3.4"])
def test_parse_probe_rejects(reply: str) -> None:
    assert _parse_probe(reply) is None


def test_decode_location() -> None:
    assert _decode_location(b"Le%C3%B3n(42.6,-5.5)()") == ("León", 42.6, -5.5)
    assert _decode_location(b"Nowhere") == ("Nowhere", None, None)


def test_discover(fake_socket) -> None:
    fake_socket.replies = [PROBE_REPLY, PROBE_REPLY]  # duplicate is dropped
    found = discover(timeout=0.01)
    assert [m["bssid"] for m in found] == ["30:30:f9:f3:ce:b8"]
    assert fake_socket.sent[0][1] == ("255.255.255.255", 8000)


def test_poll(fake_socket) -> None:
    fake_socket.replies = [
        b"I'm 2M09+77+0+V1.9.250215+30:30:f9:f3:ce:b8+192.168.1.244,45",
        _settings_ack(flags=0b0110),  # unit bit 0 => Fahrenheit
        _weather_ack(flags=1, server=0),
    ]
    state = WiseMirrorDevice("192.168.1.244").poll()
    assert state["bssid"] == "30:30:f9:f3:ce:b8"
    assert state["has_humidity_sensor"] is True
    assert state["humidity"] == 45
    assert state["unit"] == 0
    assert state["temperature_c"] == 25.0  # 77 °F
    assert state["hour_24"] is True
    assert state["day_month"] is True
    assert state["key_tone"] is False
    assert state["brightness"] == 80
    assert state["night_on"] is True
    assert state["night_start"] == (22, 30)
    assert state["night_end"] == (7, 0)
    assert state["night_light"] == 10
    assert (state["location"], state["location_lat"], state["location_lon"]) == (
        "León",
        42.6,
        -5.5,
    )
    assert state["two_day"] is True
    assert state["server"] == "no4"  # raw 0 is the app's "No4"


def test_poll_no_humidity_sensor(fake_socket) -> None:
    fake_socket.replies = [PROBE_REPLY, _settings_ack(), _weather_ack()]
    state = WiseMirrorDevice("192.168.1.244").poll()
    assert state["has_humidity_sensor"] is False
    assert state["humidity"] is None


def test_poll_unreachable(fake_socket) -> None:
    with pytest.raises(ConnectionError):
        WiseMirrorDevice("192.168.1.244", timeout=0.01, retries=1).poll()


def test_write_retries_until_ack(fake_socket) -> None:
    fake_socket.replies = [socket.timeout, _write_ack(0x03, ok=False), _write_ack(0x06)]
    assert WiseMirrorDevice("192.168.1.244").set_brightness(150) is True
    frames = [data for data, _ in fake_socket.sent]
    assert len(frames) == 3
    assert frames[0][6] == 100  # clamped
    assert fake_socket.sent[0][1] == ("192.168.1.244", 8001)


def test_write_not_acknowledged(fake_socket) -> None:
    assert WiseMirrorDevice("192.168.1.244", retries=2).set_hour24(True) is False


def test_set_location_payload(fake_socket) -> None:
    fake_socket.replies = [_write_ack(0x0B)]
    assert WiseMirrorDevice("192.168.1.244").set_location("León", 42.6, -5.5)
    frame = fake_socket.sent[0][0]
    body = b"Le%C3%B3n(42.6,-5.5)()"
    assert frame[1] == 0x0B
    assert frame[6:8] == bytes([0, len(body)])
    assert frame[8:-2] == body
    assert urllib.parse.unquote(frame[8:-2].decode()).startswith("León(")
