"""Low-level WiseMirror / Alasta mirror LAN protocol (blocking sockets).

Reverse-engineered from the WiseMirror app. See PROTOCOL.md. All calls are
synchronous; the integration runs them in the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import socket
import urllib.parse

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


def _build_frame(wire_opcode: int, payload: bytes, sub: int = 0) -> bytes:
    n = len(payload)
    hi, lo = (n >> 8) & 0xFF, n & 0xFF
    chk = (wire_opcode + hi + lo + sub + 1 + sum(payload)) & 0xFF
    return (
        bytes([0xA5, wire_opcode & 0xFF, hi, lo, sub & 0xFF, 0x01])
        + payload
        + bytes([chk, 0x5A])
    )


def _parse_probe(text: str) -> dict | None:
    """Parse a discovery/temp reply string (a0.b.a)."""
    text = text.strip()
    if not text:
        return None
    humidity = None
    main = text
    if "," in text:
        main, hum = text.split(",", 1)
        try:
            humidity = int(hum)
        except ValueError:
            humidity = None
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
    if len(fields) >= 4 and fields[2].lstrip("-").isdigit():
        out["temp"] = int(fields[1])
        out["unit"] = int(fields[2])
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
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.bind(("", 0))
    s.settimeout(timeout)
    found, seen = [], set()
    try:
        s.sendto(PROBE_TEMP, (BCAST, DISCOVERY_PORT))
        while True:
            try:
                data, addr = s.recvfrom(256)
            except TimeoutError:
                break
            d = _parse_probe(data.decode("utf-8", "ignore"))
            if d and d["bssid"] not in seen:
                seen.add(d["bssid"])
                if not d.get("address") or d["address"] == "0.0.0.0":
                    d["address"] = addr[0]
                found.append(d)
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

    # ---- low level ----
    def _probe(self) -> dict | None:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", 0))
        s.settimeout(self.timeout + 1.0)
        try:
            s.sendto(PROBE_TEMP, (self.host, DISCOVERY_PORT))
            data, _ = s.recvfrom(256)
            return _parse_probe(data.decode("utf-8", "ignore"))
        except OSError:
            return None
        finally:
            s.close()

    def _send(self, logical_id: int, payload: bytes) -> bytes:
        """Send a command/read; return the full ack frame (b'' on failure)."""
        if logical_id == 35:
            payload = bytes([len(payload)]) + payload
        frame = _build_frame(_WIRE[logical_id], payload)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", 0))
        s.settimeout(self.timeout)
        try:
            for _ in range(self.retries):
                s.sendto(frame, (self.host, CONTROL_PORT))
                try:
                    ack, _ = s.recvfrom(250)
                except TimeoutError:
                    continue
                if len(ack) > 5 and ack[5] == 1 and ack[1] == _WIRE[logical_id]:
                    return ack
            return b""
        finally:
            s.close()

    # ---- reads ----
    def poll(self) -> dict:
        """Read everything; raise ConnectionError if the mirror is unreachable."""
        probe = self._probe()
        settings = self._send(36, bytes([0]))
        weather = self._send(41, bytes([0]))
        if not probe and not settings:
            raise ConnectionError(f"WiseMirror at {self.host} not responding")

        state: dict = {"available": True, "host": self.host}
        if probe:
            state["bssid"] = probe.get("bssid") or self.bssid
            state["model"] = probe.get("model")
            state["version"] = probe.get("version")
            hum = probe.get("humidity")
            state["has_humidity_sensor"] = bool(hum)  # 0 => no sensor
            state["humidity"] = hum if hum else None
        if settings and settings[0] == 0xA5:
            b = settings
            flags = b[6]
            unit = (flags >> 3) & 1
            state["key_tone"] = bool(flags & 1)
            state["hour_24"] = bool((flags >> 1) & 1)
            state["day_month"] = bool((flags >> 2) & 1)
            state["unit"] = unit  # 1=°C, 0=°F
            state["brightness"] = b[7]
            state["night_on"] = bool(b[30])
            state["night_start"] = (b[31], b[32])
            state["night_end"] = (b[33], b[34])
            state["night_light"] = b[35]
            ln = (b[36] << 8) | b[37]
            name, lat, lon = _decode_location(b[38 : 38 + ln])
            state["location"] = name
            state["location_lat"] = lat
            state["location_lon"] = lon
            # indoor temperature, normalised to °C
            if probe and probe.get("temp") is not None:
                t = probe["temp"]
                state["temperature_c"] = (
                    round((t - 32) * 5 / 9, 1) if unit == 0 else float(t)
                )
        if weather and weather[0] == 0xA5:
            wf = weather[6]
            state["two_day"] = bool(wf & 1)
            state["today_weather"] = (wf >> 1) & 1
            state["server"] = RAW_TO_SERVER.get(weather[7], "auto")
            state["server_raw"] = weather[7]
        return state

    # ---- writes (return True on ack) ----
    def _ok(self, logical_id: int, payload: bytes) -> bool:
        return bool(self._send(logical_id, payload))

    def set_brightness(self, value: int) -> bool:
        return self._ok(6, bytes([max(0, min(100, int(value)))]))

    def set_night_brightness(self, value: int) -> bool:
        return self._ok(34, bytes([max(0, min(100, int(value)))]))

    def set_hour24(self, on: bool) -> bool:
        return self._ok(2, bytes([1 if on else 0]))

    def set_daymonth(self, on: bool) -> bool:
        return self._ok(3, bytes([1 if on else 0]))

    def set_key_tone(self, on: bool) -> bool:
        return self._ok(1, bytes([1 if on else 0]))

    def set_unit_celsius(self, celsius: bool) -> bool:
        return self._ok(4, bytes([1 if celsius else 0]))

    def set_night_mode(self, on: bool) -> bool:
        return self._ok(32, bytes([1 if on else 0]))

    def set_night_time(self, sh: int, sm: int, eh: int, em: int) -> bool:
        return self._ok(33, bytes([sh & 0xFF, sm & 0xFF, eh & 0xFF, em & 0xFF]))

    def set_weather(self, two_day: bool, server_raw: int) -> bool:
        # payload = [rollScreen|(todayWeather<<1), server, 0, 0]; todayWeather kept 0
        return self._ok(40, bytes([1 if two_day else 0, server_raw & 0xFF, 0, 0]))

    def set_location(
        self, name: str, lat: float, lon: float, accu_key: str = ""
    ) -> bool:
        body = f"{urllib.parse.quote(name)}({lat},{lon})({accu_key})".encode()
        payload = bytes([(len(body) >> 8) & 0xFF, len(body) & 0xFF]) + body
        return self._ok(31, payload)
