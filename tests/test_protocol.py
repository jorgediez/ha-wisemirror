"""Tests for the low-level protocol (no Home Assistant involved)."""

from __future__ import annotations

import socket
import threading
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


def _frame(opcode: int, payload: bytes, declared: int | None = None) -> bytes:
    """A reply frame with a valid checksum; the declared length can be set apart."""
    n = len(payload) if declared is None else declared
    head = bytes([0xA5, opcode, n >> 8, n & 0xFF, 0, 1])
    return head + payload + bytes([(sum(head[1:]) + sum(payload)) & 0xFF, 0x5A])


def _settings_ack(
    flags: int = 0b1110,
    brightness: int = 80,
    location: str = "Le%C3%B3n(42.6,-5.5)()",
) -> bytes:
    """A read-settings (0x10) reply laid out like the real mirror's.

    Like the real one, it declares one byte fewer than it sends.
    """
    loc = location.encode()
    p = bytearray(32)
    p[0], p[1] = flags, brightness
    p[24] = 1  # night mode on
    p[25:29] = bytes([22, 30, 7, 0])
    p[29] = 10  # night light
    p[30], p[31] = len(loc) >> 8, len(loc) & 0xFF
    payload = bytes(p) + loc
    return _frame(0x10, payload, declared=len(payload) - 1)


def _weather_ack(flags: int = 1, server: int = 0) -> bytes:
    return _frame(0x16, bytes([flags, server, 0, 0, 0, 0]))


def _write_ack(opcode: int, ok: bool = True) -> bytes:
    frame = bytearray(_frame(opcode, bytes([0])))
    if not ok:
        frame[5] = 0
        frame[-2] = (frame[-2] - 1) & 0xFF
    return bytes(frame)


# Replies captured from a 2M09 on firmware V1.9.250215 (2026-11-19). The location
# is swapped for a public one, with the length bytes and checksum redone.
# Everything else is as the mirror sent it, including the settings reply
# declaring one byte fewer than it sends (75 for a payload of 76).
_LOCATION = b"Madrid(40.4168,-3.7038)()"
_SETTINGS_PAYLOAD = (
    bytes.fromhex("2e1e1e06")
    + bytes(20)
    + bytes.fromhex("0115190b0005")
    + bytes([0, len(_LOCATION)])
    + _LOCATION
)
REAL_SETTINGS = _frame(0x10, _SETTINGS_PAYLOAD, declared=len(_SETTINGS_PAYLOAD) - 1)
REAL_WEATHER = _frame(
    0x16, bytes.fromhex("00ff000000") + bytes([len(_LOCATION)]) + _LOCATION
)
# Setting the display brightness to 30, verbatim.
REAL_WRITE_ACK = bytes.fromhex("a506000100011e265a")


class FakeSocket:
    """Stands in for socket.socket; replies come from a shared queue.

    A reply is the bytes, (bytes, source address) for an unconnected socket,
    or an exception to raise.
    """

    replies: list = []
    sent: list[tuple[bytes, tuple[str, int]]] = []
    send_error: OSError | None = None
    connect_error: OSError | None = None

    def __init__(self, *args, **kwargs) -> None:
        self.peer: tuple[str, int] | None = None

    def setsockopt(self, *args) -> None:
        pass

    def bind(self, addr) -> None:
        pass

    def connect(self, addr) -> None:
        if FakeSocket.connect_error is not None:
            raise FakeSocket.connect_error
        self.peer = addr

    def settimeout(self, t) -> None:
        pass

    def send(self, data: bytes) -> None:
        self.sendto(data, self.peer)

    def sendto(self, data: bytes, addr) -> None:
        if FakeSocket.send_error is not None:
            raise FakeSocket.send_error
        FakeSocket.sent.append((data, addr))

    def recvfrom(self, n: int):
        if not FakeSocket.replies:
            raise TimeoutError
        reply = FakeSocket.replies.pop(0)
        if isinstance(reply, BaseException) or (
            isinstance(reply, type) and issubclass(reply, BaseException)
        ):
            raise reply
        if isinstance(reply, tuple):
            return reply
        return reply, self.peer or ("192.168.1.244", 8000)

    def recv(self, n: int) -> bytes:
        return self.recvfrom(n)[0]

    def close(self) -> None:
        pass


@pytest.fixture
def fake_socket():
    FakeSocket.replies = []
    FakeSocket.sent = []
    FakeSocket.send_error = None
    FakeSocket.connect_error = None
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


def test_poll_real_replies(fake_socket) -> None:
    fake_socket.replies = [PROBE_REPLY, REAL_SETTINGS, REAL_WEATHER]
    state = WiseMirrorDevice("192.168.1.244").poll()
    assert state["unit"] == 1
    assert state["hour_24"] is True
    assert state["day_month"] is True
    assert state["key_tone"] is False
    assert state["brightness"] == 30
    assert state["night_on"] is True
    assert state["night_start"] == (21, 25)
    assert state["night_end"] == (11, 0)
    assert state["night_light"] == 5
    assert (state["location"], state["location_lat"], state["location_lon"]) == (
        "Madrid",
        40.4168,
        -3.7038,
    )
    assert state["two_day"] is False
    assert state["server"] == "auto"


def test_write_real_ack(fake_socket) -> None:
    fake_socket.replies = [REAL_WRITE_ACK]
    assert WiseMirrorDevice("192.168.1.244").set_brightness(30) is True


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(
            lambda f: f[:-2] + bytes([(f[-2] + 1) & 0xFF]) + f[-1:], id="checksum"
        ),
        pytest.param(lambda f: f[:-1] + b"\x00", id="trailer"),
        pytest.param(lambda f: b"\x00" + f[1:], id="header"),
        pytest.param(lambda f: f[:5], id="truncated"),
    ],
)
def test_a_damaged_reply_is_not_an_ack(fake_socket, corrupt) -> None:
    fake_socket.replies = [corrupt(REAL_WRITE_ACK), REAL_WRITE_ACK]
    assert WiseMirrorDevice("192.168.1.244").set_brightness(30) is True
    assert len(fake_socket.sent) == 2  # the damaged reply was retried


@pytest.mark.parametrize("payload_len", [0, 1, 2, 10, 29, 30, 31, 33])
def test_poll_short_settings_reply(fake_socket, payload_len: int) -> None:
    """A model sending less than the 2M09 must not break the poll."""
    short = _frame(0x10, _SETTINGS_PAYLOAD[:payload_len])
    fake_socket.replies = [PROBE_REPLY, short, _frame(0x16, b"\x01")]
    state = WiseMirrorDevice("192.168.1.244").poll()
    assert state["available"] is True
    assert ("brightness" in state) is (payload_len >= 2)
    assert ("night_light" in state) is (payload_len >= 30)
    assert "two_day" not in state  # weather reply too short too


def test_poll_location_longer_than_the_reply(fake_socket) -> None:
    payload = bytearray(_SETTINGS_PAYLOAD)
    payload[30:32] = bytes([0x01, 0x00])  # claims 256 bytes
    fake_socket.replies = [PROBE_REPLY, _frame(0x10, bytes(payload)), REAL_WEATHER]
    state = WiseMirrorDevice("192.168.1.244").poll()
    assert state["location"] == "Madrid"


@pytest.mark.parametrize(
    "reply",
    [
        "I'm 2M09+hot+1+V1+30:30:f9:f3:ce:b8+192.168.1.244",
        "I'm 2M09+25+x+V1+30:30:f9:f3:ce:b8+192.168.1.244",
        "I'm 2M09+25+1+V1+30:30:f9:f3:ce:b8+192.168.1.244,wet",
    ],
)
def test_parse_probe_tolerates_bad_numbers(reply: str) -> None:
    parsed = _parse_probe(reply)
    assert parsed is not None
    assert parsed["bssid"] == "30:30:f9:f3:ce:b8"


def test_discover_skips_a_garbled_reply(fake_socket) -> None:
    fake_socket.replies = [
        (b"I'm 2M09+hot+cold+V1+aa:bb:cc:dd:ee:ff+10.0.0.9", ("10.0.0.9", 8000)),
        (b"\xff\xfe garbage", ("10.0.0.8", 8000)),
        (PROBE_REPLY, ("192.168.1.244", 8000)),
    ]
    found = discover(timeout=0.01)
    assert [m["bssid"] for m in found] == ["aa:bb:cc:dd:ee:ff", "30:30:f9:f3:ce:b8"]


def test_discover_uses_the_replys_source_address(fake_socket) -> None:
    """A reply can claim any address; reach the device that answered."""
    fake_socket.replies = [(PROBE_REPLY, ("192.168.1.77", 8000))]
    (mirror,) = discover(timeout=0.01)
    assert mirror["address"] == "192.168.1.77"


def test_network_errors(fake_socket) -> None:
    fake_socket.send_error = OSError(101, "Network is unreachable")
    device = WiseMirrorDevice("192.168.1.244", timeout=0.01)
    with pytest.raises(ConnectionError):
        device.poll()
    assert device.set_brightness(30) is False
    assert discover(timeout=0.01) == []


def test_no_route_to_the_mirror(fake_socket) -> None:
    """Linux refuses to connect a UDP socket to an address it has no route to."""
    fake_socket.connect_error = OSError(101, "Network is unreachable")
    device = WiseMirrorDevice("192.168.1.244")
    with pytest.raises(ConnectionError):
        device.poll()
    assert device.set_brightness(30) is False
    assert fake_socket.sent == []


def test_refused_reply_is_no_reply(fake_socket) -> None:
    """Linux reports an ICMP port unreachable on the next read of the socket."""
    fake_socket.replies = [ConnectionRefusedError]
    assert WiseMirrorDevice("192.168.1.244").set_brightness(30) is False
    assert len(fake_socket.sent) == 1  # nobody is listening: no point retrying


def test_poll_and_writes_do_not_interleave() -> None:
    """The mirror handles one command at a time: a write waits for a poll."""
    device = WiseMirrorDevice("192.168.1.244")
    in_poll, release = threading.Event(), threading.Event()
    sent: list[int] = []

    def probe() -> dict:
        in_poll.set()
        release.wait(5)
        return {"bssid": "30:30:f9:f3:ce:b8", "model": "2M09"}

    def send(logical_id: int, payload: bytes) -> bytes:
        sent.append(logical_id)
        return b"\x00"

    with (
        patch.object(device, "_probe", probe),
        patch.object(device, "_send", send),
    ):
        poll = threading.Thread(target=device.poll)
        write = threading.Thread(target=device.set_brightness, args=(5,))
        poll.start()
        try:
            assert in_poll.wait(5)
            write.start()
            write.join(0.3)
            sent_during_poll = list(sent)
        finally:
            release.set()
            poll.join(5)
            if write.ident is not None:  # started
                write.join(5)
    assert sent_during_poll == []  # the write waited for the poll
    assert sent == [36, 41, 6]
