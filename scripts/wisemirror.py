#!/usr/bin/env python3
"""
wisemirror.py - control an Alasta / WiseMirror weather mirror over the LAN.

Reverse-engineered from the WiseMirror app (com.smartteam.smartmirror).
See docs/PROTOCOL.md for the full spec. No cloud, no auth - pure local UDP.

Usage:
    python wisemirror.py discover                  # find mirror IP + indoor temp/humidity
    python wisemirror.py set --ip 192.168.1.50 hour24 1
    python wisemirror.py set --ip 192.168.1.50 tempunit 0
    python wisemirror.py set --ip 192.168.1.50 brightness 80
    python wisemirror.py set --ip 192.168.1.50 sleeptime 22 30 7 0
    python wisemirror.py raw --ip 192.168.1.50 4 01          # logical opcode 4, payload hex
    python wisemirror.py temp                       # JSON: indoor temp/humidity (for HA)
"""

import argparse
import json
import socket
import urllib.parse

BCAST = "255.255.255.255"
DISCOVERY_PORT = 8000
CONTROL_PORT = 8001  # UDP; commands + ack (WifiBaseManager.r)
PROBE_NEW = b"Are you a new device that link to LEDWiFi"
PROBE_TEMP = b"What is the temperature of LEDWifi"
MODEL_TAGS = ("8J11", "8J12", "2K02", "2M09")

# logical id -> wire opcode (a0.a.e); only the ones we expose
LOGICAL_TO_WIRE = {
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
    0: 0x15,
}


def build_frame(wire_opcode: int, payload: bytes, sub: int = 0) -> bytes:
    """a0.a.c: 0xA5 | op | lenHi | lenLo | sub | 0x01 | payload | checksum | 0x5A"""
    n = len(payload)
    hi, lo = (n >> 8) & 0xFF, n & 0xFF
    chk = (wire_opcode + hi + lo + sub + 1 + sum(payload)) & 0xFF
    return (
        bytes([0xA5, wire_opcode & 0xFF, hi, lo, sub & 0xFF, 0x01])
        + payload
        + bytes([chk, 0x5A])
    )


def parse_reply(text: str):
    """a0.b.a parser. Returns dict or None."""
    text = text.strip()
    if not text:
        return None
    humidity = None
    main = text
    if "," in text:
        main, hum = text.split(",", 1)
        try:
            humidity = int(hum)  # raw; app clamps to 1..99 for display
        except ValueError:
            humidity = None
    fields = main.split("+")
    if len(fields) < 2:
        return None
    head = fields[0]  # e.g. "I'm 2M09"
    if not any(tag in head for tag in MODEL_TAGS):
        return None
    # model is the head token matching a known tag (a literal "I'm" prefixes it)
    model = next(
        (t for t in head.split() if any(tag in t for tag in MODEL_TAGS)),
        head.split()[-1],
    )
    out = {
        "model": model,
        "bssid": fields[-2],
        "address": fields[-1],
        "humidity": humidity,
    }
    # temp probe replies carry temp/unit/version in fields[1..3]
    if len(fields) >= 4 and fields[2].lstrip("-").isdigit():
        out["temp"] = int(fields[1])
        out["unit"] = int(fields[2])
        out["version"] = fields[3]
    return out


def discover(probe: bytes = PROBE_TEMP, listen_port: int = 4026, timeout: float = 2.0):
    """Broadcast a probe and collect replies. Returns list of dicts."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        s.bind(("", listen_port))
    except OSError:
        s.bind(("", 0))  # fall back to ephemeral port
    s.settimeout(timeout)
    s.sendto(probe, (BCAST, DISCOVERY_PORT))
    found, seen = [], set()
    try:
        while True:
            data, addr = s.recvfrom(256)
            d = parse_reply(data.decode("utf-8", "ignore"))
            if d and d["bssid"] not in seen:
                seen.add(d["bssid"])
                # A mirror without an address of its own reports 0.0.0.0; use the
                # address the reply came from. A comparison, not a bind.
                if not d.get("address") or d["address"] == "0.0.0.0":  # noqa: S104
                    d["address"] = addr[0]
                found.append(d)
    except TimeoutError:
        pass
    finally:
        s.close()
    return found


def send_command(
    ip: str, logical_id: int, payload: bytes, timeout: float = 1.0, retries: int = 4
):
    """UDP to mirror:8001 with one framed command; wait for ack (WifiBaseManager.r).

    Returns (ok, ack_bytes): ok is True when the mirror echoes ack[5]==1 and the
    expected wire opcode in ack[1]."""
    if logical_id == 35:  # device name: wire layer prepends a length byte
        payload = bytes([len(payload)]) + payload
    wire = LOGICAL_TO_WIRE.get(logical_id)
    if wire is None:
        raise ValueError(f"unknown logical opcode {logical_id}")
    frame = build_frame(wire, payload)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", 0))
    s.settimeout(timeout)
    try:
        for _ in range(retries):
            s.sendto(frame, (ip, CONTROL_PORT))
            try:
                ack, _ = s.recvfrom(250)
            except TimeoutError:
                continue
            ok = len(ack) > 5 and ack[5] == 1 and ack[1] == wire
            return ok, ack
        return False, b""
    finally:
        s.close()


def area_payload(name: str, lat: float, lon: float, accu_key: str = "") -> bytes:
    """z.d.b('<urlencoded name>(lat,lon)(key)') -> 2-byte len prefix + utf8."""
    s = f"{urllib.parse.quote(name)}({lat},{lon})({accu_key})".encode()
    return bytes([(len(s) >> 8) & 0xFF, len(s) & 0xFF]) + s


# name -> (logical_id, payload-builder from CLI args)
SETTERS = {
    "keytone": (1, lambda a: bytes([int(a[0])])),
    "hour24": (2, lambda a: bytes([int(a[0])])),  # 0=12h, 1=24h
    "datefmt": (3, lambda a: bytes([int(a[0])])),  # 0=MM/DD, 1=DD/MM
    "tempunit": (4, lambda a: bytes([int(a[0])])),  # 0=°F, 1=°C (confirmed on hw)
    "brightness": (6, lambda a: bytes([max(0, min(100, int(a[0])))])),
    "sleepmode": (32, lambda a: bytes([int(a[0])])),
    "sleeptime": (33, lambda a: bytes([int(a[0]), int(a[1]), int(a[2]), int(a[3])])),
    "light": (34, lambda a: bytes([int(a[0])])),
    "weeklang": (44, lambda a: bytes([int(a[0])])),
    "readsettings": (36, lambda a: bytes([0])),
    "area": (
        31,
        lambda a: area_payload(
            a[0], float(a[1]), float(a[2]), a[3] if len(a) > 3 else ""
        ),
    ),
    # weather: z.d.a(rollScreen, todayWeather, server) -> [bit0|bit1<<1, server, 0, 0]
    #   bit0 rollScreen = "weather for two days" display toggle (1=on)
    #   bit1 todayWeather = separate flag, not exposed in app UI (keep 0)
    #   server: 255=Auto, 0..4 = No1..No5
    # args: <twoday 0|1> [server]   (todayWeather forced 0)
    "weather": (
        40,
        lambda a: bytes([int(a[0]) & 1, int(a[1]) if len(a) > 1 else 255, 0, 0]),
    ),
}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("discover")
    sub.add_parser("temp")

    sp = sub.add_parser("set")
    sp.add_argument("--ip", required=True)
    sp.add_argument("setting", choices=list(SETTERS))
    sp.add_argument("args", nargs="*")

    rp = sub.add_parser("raw")
    rp.add_argument("--ip", required=True)
    rp.add_argument("logical", type=int)
    rp.add_argument("hexpayload")

    a = ap.parse_args()

    if a.cmd == "discover":
        for d in discover():
            print(json.dumps(d))
        return

    if a.cmd == "temp":  # HA-friendly single JSON object
        res = discover()
        print(json.dumps(res[0] if res else {}))
        return

    if a.cmd == "set":
        logical, build = SETTERS[a.setting]
        ok, ack = send_command(a.ip, logical, build(a.args))
        print(f"sent {a.setting}: {'OK' if ok else 'NO/UNCONFIRMED'}  ack={ack.hex()}")
        return

    if a.cmd == "raw":
        ok, ack = send_command(a.ip, a.logical, bytes.fromhex(a.hexpayload))
        print(f"{'OK' if ok else 'NO/UNCONFIRMED'}  ack={ack.hex()}")
        return


if __name__ == "__main__":
    main()
