"""Low-level WiseMirror / Alasta mirror LAN protocol (blocking sockets).

Reverse-engineered from the WiseMirror app. See PROTOCOL.md. All calls are
synchronous; the integration runs them in the executor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
import socket
import threading
import urllib.parse

_LOGGER = logging.getLogger(__name__)

DISCOVERY_PORT = 8000  # UDP, ASCII probe -> reply
CONTROL_PORT = 8001  # UDP, framed commands + ack
BCAST = "255.255.255.255"
PROBE_TEMP = b"What is the temperature of LEDWifi"
MODEL_TAGS = ("8J11", "8J12", "2K02", "2M09")

# logical id -> wire opcode (a0.a.e)
_WIRE = {
    1: 0x01,
    2: 0x02,
    3: 0x03,
    4: 0x04,
    6: 0x06,
    31: 0x0B,
    32: 0x0C,
    33: 0x0D,
    34: 0x0E,
    35: 0x0F,
    36: 0x10,
    40: 0x30,
    41: 0x16,
    44: 0x31,
}

# weather server: option key (app label "Auto", "No1".."No5") -> raw byte  (and reverse)
SERVER_TO_RAW = {"auto": 255, "no1": 1, "no2": 2, "no3": 3, "no4": 0, "no5": 4}
RAW_TO_SERVER = {v: k for k, v in SERVER_TO_RAW.items()}


_HEADER = 0xA5
_TRAILER = 0x5A

# Offsets into the payload of the read-settings (0x10) reply.
_S_FLAGS = 0
_S_BRIGHTNESS = 1
_S_NIGHT_ON = 24
_S_NIGHT_TIMES = 25  # start hour, start minute, end hour, end minute
_S_NIGHT_LIGHT = 29
_S_LOCATION_LEN = 30  # 2 bytes, big-endian, then the location itself
# Offsets into the payload of the read-weather (0x16) reply.
_W_FLAGS = 0
_W_SERVER = 1


def _build_frame(wire_opcode: int, payload: bytes, sub: int = 0) -> bytes:
    n = len(payload)
    hi, lo = (n >> 8) & 0xFF, n & 0xFF
    chk = (wire_opcode + hi + lo + sub + 1 + sum(payload)) & 0xFF
    return (
        bytes([0xA5, wire_opcode & 0xFF, hi, lo, sub & 0xFF, 0x01])
        + payload
        + bytes([chk, 0x5A])
    )


def _ack_payload(ack: bytes, wire_opcode: int) -> bytes | None:
    """Return the payload of an acknowledging reply to wire_opcode, else None.

    Checks the header, opcode, ack flag, checksum and trailer, but not the length
    the frame declares: a 2M09 declares one byte fewer than it sends in its
    settings reply, while its checksum covers every byte sent.
    """
    if (
        len(ack) < 8
        or ack[0] != _HEADER
        or ack[-1] != _TRAILER
        or ack[1] != wire_opcode
        or ack[5] != 1
    ):
        return None
    payload = ack[6:-2]
    if (sum(ack[1:6]) + sum(payload)) & 0xFF != ack[-2]:
        return None
    return payload


def _int(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


def _parse_probe(text: str) -> dict | None:
    """Parse a discovery/temp reply string (a0.b.a)."""
    text = text.strip()
    if not text:
        return None
    humidity = None
    main = text
    if "," in text:
        main, hum = text.split(",", 1)
        humidity = _int(hum)
    fields = main.split("+")
    if len(fields) < 2:
        return None
    head = fields[0]
    if not any(tag in head for tag in MODEL_TAGS):
        return None
    model = next(
        (t for t in head.split() if any(tag in t for tag in MODEL_TAGS)),
        head.split()[-1],
    )
    out = {
        "model": model,
        "bssid": fields[-2],
        "address": fields[-1],
        "humidity": humidity,
        "temp": None,
        "unit": None,
        "version": None,
    }
    if len(fields) >= 4:
        temp, unit = _int(fields[1]), _int(fields[2])
        if temp is not None and unit is not None:
            out["temp"] = temp
            out["unit"] = unit
            out["version"] = fields[3]
    return out


def _decode_location(raw: bytes) -> tuple[str, float | None, float | None]:
    """'Le%C3%B3n(42.6,-5.5)()[..]' -> ('León', 42.6, -5.5)."""
    try:
        s = urllib.parse.unquote(raw.decode("utf-8", "ignore"))
    except ValueError:
        return "", None, None
    name = s.split("(")[0].strip()
    lat = lon = None
    m = re.search(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", s)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
    return name, lat, lon


def discover(timeout: float = 2.5) -> list[dict]:
    """Broadcast probe; return list of mirrors found on the LAN."""
    found, seen = [], set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError as err:
        _LOGGER.debug("Cannot open a socket to discover mirrors: %s", err)
        return found
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", 0))
        s.settimeout(timeout)
        s.sendto(PROBE_TEMP, (BCAST, DISCOVERY_PORT))
        while True:
            data, addr = s.recvfrom(256)
            d = _parse_probe(data.decode("utf-8", "ignore"))
            if d and d["bssid"] not in seen:
                seen.add(d["bssid"])
                # Reach the mirror at the address its reply came from, not the one
                # it states: a mirror can state 0.0.0.0, and any device on the LAN
                # can state any address.
                d["address"] = addr[0]
                found.append(d)
    except TimeoutError:
        pass
    except OSError as err:
        _LOGGER.debug("Discovery stopped: %s", err)
    finally:
        s.close()
    return found


@dataclass
class WiseMirrorDevice:
    """One mirror, addressed by IP (with bssid as the stable identity)."""

    host: str
    bssid: str | None = None
    timeout: float = 1.0
    retries: int = 4
    # The mirror handles one command at a time: a poll and a write run in
    # different executor threads, so they take turns.
    _lock: threading.Lock = field(
        default_factory=threading.Lock, init=False, repr=False, compare=False
    )

    # ---- low level ----
    def _socket(self, port: int, timeout: float) -> socket.socket:
        """Open a UDP socket connected to the mirror.

        Connected, the socket only receives what comes from that address and
        port, which is where the mirror answers from.
        """
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.settimeout(timeout)
            s.connect((self.host, port))
        except OSError:
            s.close()
            raise
        return s

    def _probe(self) -> dict | None:
        try:
            s = self._socket(DISCOVERY_PORT, self.timeout + 1.0)
        except OSError as err:
            _LOGGER.debug("Cannot reach %s: %s", self.host, err)
            return None
        try:
            s.send(PROBE_TEMP)
            data = s.recv(256)
        except OSError as err:
            _LOGGER.debug("No probe reply from %s: %s", self.host, err)
            return None
        finally:
            s.close()
        return _parse_probe(data.decode("utf-8", "ignore"))

    def _send(self, logical_id: int, payload: bytes) -> bytes | None:
        """Send a command/read; return the ack's payload, or None without one."""
        if logical_id == 35:
            payload = bytes([len(payload)]) + payload
        wire = _WIRE[logical_id]
        frame = _build_frame(wire, payload)
        try:
            s = self._socket(CONTROL_PORT, self.timeout)
        except OSError as err:
            _LOGGER.debug("Cannot reach %s: %s", self.host, err)
            return None
        try:
            for _ in range(self.retries):
                s.send(frame)
                try:
                    ack = s.recv(512)
                except TimeoutError:
                    continue
                reply = _ack_payload(ack, wire)
                if reply is not None:
                    return reply
                _LOGGER.debug("Ignoring reply %s from %s", ack.hex(), self.host)
            return None
        except OSError as err:
            # Network unreachable, or the port refused (reported on the next read).
            _LOGGER.debug("Command %#04x to %s failed: %s", wire, self.host, err)
            return None
        finally:
            s.close()

    # ---- reads ----
    def poll(self) -> dict:
        """Read everything; raise ConnectionError if the mirror is unreachable."""
        with self._lock:
            probe = self._probe()
            settings = self._send(36, bytes([0]))
            weather = self._send(41, bytes([0]))
        if not probe and settings is None:
            raise ConnectionError(f"WiseMirror at {self.host} not responding")

        state: dict = {"available": True, "host": self.host}
        if probe:
            state["bssid"] = probe.get("bssid") or self.bssid
            state["model"] = probe.get("model")
            state["version"] = probe.get("version")
            hum = probe.get("humidity")
            state["has_humidity_sensor"] = bool(hum)  # 0 => no sensor
            state["humidity"] = hum if hum else None
        # Each field is read only if the reply reaches it: other models may send
        # less than the 2M09, and a missing field is better than a failed poll.
        if settings is not None and len(settings) > _S_BRIGHTNESS:
            flags = settings[_S_FLAGS]
            unit = (flags >> 3) & 1
            state["key_tone"] = bool(flags & 1)
            state["hour_24"] = bool((flags >> 1) & 1)
            state["day_month"] = bool((flags >> 2) & 1)
            state["unit"] = unit  # 1=°C, 0=°F
            state["brightness"] = settings[_S_BRIGHTNESS]
            # indoor temperature, normalised to °C
            if probe and probe.get("temp") is not None:
                t = probe["temp"]
                state["temperature_c"] = (
                    round((t - 32) * 5 / 9, 1) if unit == 0 else float(t)
                )
        if settings is not None and len(settings) > _S_NIGHT_LIGHT:
            sh, sm, eh, em = settings[_S_NIGHT_TIMES : _S_NIGHT_TIMES + 4]
            state["night_on"] = bool(settings[_S_NIGHT_ON])
            state["night_start"] = (sh, sm)
            state["night_end"] = (eh, em)
            state["night_light"] = settings[_S_NIGHT_LIGHT]
        if settings is not None and len(settings) >= _S_LOCATION_LEN + 2:
            start = _S_LOCATION_LEN + 2
            ln = (settings[_S_LOCATION_LEN] << 8) | settings[_S_LOCATION_LEN + 1]
            name, lat, lon = _decode_location(settings[start : start + ln])
            state["location"] = name
            state["location_lat"] = lat
            state["location_lon"] = lon
        if weather is not None and len(weather) > _W_SERVER:
            wf = weather[_W_FLAGS]
            state["two_day"] = bool(wf & 1)
            state["today_weather"] = (wf >> 1) & 1
            state["server"] = RAW_TO_SERVER.get(weather[_W_SERVER], "auto")
            state["server_raw"] = weather[_W_SERVER]
        return state

    # ---- writes (return True on ack) ----
    def _ok(self, logical_id: int, payload: bytes) -> bool:
        with self._lock:
            return self._send(logical_id, payload) is not None

    def set_brightness(self, value: int) -> bool:
        """Set the display brightness (0-100)."""
        return self._ok(6, bytes([max(0, min(100, int(value)))]))

    def set_night_brightness(self, value: int) -> bool:
        """Set the night-mode brightness (0-100)."""
        return self._ok(34, bytes([max(0, min(100, int(value)))]))

    def set_hour24(self, on: bool) -> bool:
        """Switch the clock between 24-hour and 12-hour."""
        return self._ok(2, bytes([1 if on else 0]))

    def set_daymonth(self, on: bool) -> bool:
        """Show the date as day/month rather than month/day."""
        return self._ok(3, bytes([1 if on else 0]))

    def set_key_tone(self, on: bool) -> bool:
        """Turn the key beep on or off."""
        return self._ok(1, bytes([1 if on else 0]))

    def set_unit_celsius(self, celsius: bool) -> bool:
        """Show temperatures in Celsius rather than Fahrenheit."""
        return self._ok(4, bytes([1 if celsius else 0]))

    def set_night_mode(self, on: bool) -> bool:
        """Turn night mode on or off."""
        return self._ok(32, bytes([1 if on else 0]))

    def set_night_time(self, sh: int, sm: int, eh: int, em: int) -> bool:
        """Set when night mode starts and ends (hours, minutes)."""
        return self._ok(33, bytes([sh & 0xFF, sm & 0xFF, eh & 0xFF, em & 0xFF]))

    def set_weather(self, two_day: bool, server_raw: int) -> bool:
        """Set two-day weather and the weather server in one command."""
        # payload = [rollScreen|(todayWeather<<1), server, 0, 0]; todayWeather kept 0
        return self._ok(40, bytes([1 if two_day else 0, server_raw & 0xFF, 0, 0]))

    def set_location(
        self, name: str, lat: float, lon: float, accu_key: str = ""
    ) -> bool:
        """Set the location the mirror shows weather for."""
        body = f"{urllib.parse.quote(name)}({lat},{lon})({accu_key})".encode()
        payload = bytes([(len(body) >> 8) & 0xFF, len(body) & 0xFF]) + body
        return self._ok(31, payload)
