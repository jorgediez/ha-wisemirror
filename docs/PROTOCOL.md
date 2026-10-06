# WiseMirror / Alasta mirror — local LAN protocol

Reverse-engineered from the WiseMirror Android app (`com.smartteam.smartmirror`). All control is
**local on your Wi‑Fi** — no cloud auth. `praycloud.net` / `api.accuweather.com` are only used by the
phone to look up weather/location text; the mirror itself is driven directly over UDP on your LAN.

Validated end-to-end against an Alasta mirror, model `2M09`, firmware `V1.9.250215`.

Two transports exist in the app: **BLE** (for first-time setup) and **Wi‑Fi** (normal use). This doc
covers the Wi‑Fi path, which is what HomeAssistant will use. The byte framing is identical on both.

---

## 1. Discovery + indoor temperature  (UDP, broadcast)

The phone broadcasts a plain-ASCII probe to **`255.255.255.255:8000`** and the mirror answers with a
`+`-delimited string. Source/listen ports the app uses: `4025` (new-device) and `4026` (temp/old).

| Purpose      | Probe string sent to `255.255.255.255:8000`      | listen port |
|--------------|--------------------------------------------------|-------------|
| Find device  | `Are you a new device that link to LEDWiFi`      | 4025        |
| Find (old)   | `Are you a old device that link to LEDWiFi`      | 4026        |
| **Temp/hum** | `What is the temperature of LEDWifi`             | 4026        |

### Reply format (parser `a0.b.a`)
```
"I'm <MODEL>+<temp>+<unit>+<version>+<bssid>+<address>[,<humidity>]"
REAL capture (confirmed against hardware, model 2M09):
  I'm 2M09+25+1+V1.9.250215+30:30:f9:f3:ce:b8+192.168.1.244,0
```
- The head field is a literal `I'm ` prefix + the model token; the model must contain one of
  `8J11`, `8J12`, `2K02`, `2M09` or the reply is ignored. `bssid` is already a colon MAC.
- Observed: `temp=25`, `unit=1`. Since 25 is clearly an indoor Celsius reading, on this device
  **`unit=1` corresponds to °C** (i.e. the SendTempUnit 0/1 mapping is likely 1=°C, 0=°F — the
  opposite of the initial guess; confirm by toggling). `humidity` came back `0` on this unit.
- For the **temp** probe: `temp = field[1]`, `unit = field[2]`, `version = field[3]`.
- `bssid = field[-2]`, `address = field[-1]` (the mirror's LAN IP — use this for control).
- `humidity` (1–99) is the part after the comma, if present.

This probe alone is enough to feed **indoor temperature + humidity** sensors into HomeAssistant,
with no TCP connection required.

---

## 2. Control  (UDP to `<mirror_ip>:8001`)

Send one framed command as a **UDP datagram to `<mirror_ip>:8001`** (`WifiBaseManager.r`), from a
local socket bound to a random port, with an ~800 ms timeout. The mirror replies with an ack
datagram: **success = `ack[5] == 1`** and `ack[1]` echoes the wire opcode. The app retries on timeout.
(The TCP port `8408` seen in the app is only for AP/SoftAP provisioning at `192.168.4.1`, not normal LAN use.)

### Frame format (`a0.a.c`)
```
offset  value
  0      0xA5                      header
  1      <wire opcode>             see table
  2      (payloadLen >> 8) & 0xFF  length, big-endian
  3       payloadLen       & 0xFF
  4      <sub>  (always 0x00)
  5      0x01                      constant
  6..    payload bytes
  N-2    checksum = (b[1]+b[2]+b[3]+b[4]+b[5] + sum(payload)) & 0xFF
  N-1    0x5A                      trailer
total length = payloadLen + 8
```
(Sum the payload as plain unsigned bytes; the `&0xFF` makes signed/unsigned equivalent.)

> Note: BLE additionally fragments this frame into 20-byte chunks (`[randId, totalLen, offset, ...17B]`).
> Wi‑Fi (UDP) does **not** — the whole frame goes in one datagram. Ignore the chunking for Wi‑Fi.

### Logical → wire opcode map (`a0.a.e`)
The app calls commands by a *logical id*; `e()` converts it to the *wire opcode* placed in byte[1].

| Logical id (what app code uses) | Wire opcode (byte[1]) | Meaning |
|---|---|---|
| 1  | 0x01 | Key tone (beep) |
| 2  | 0x02 | Hour format |
| 3  | 0x03 | Date format (day/month order) |
| 4  | 0x04 | Temperature unit |
| 6  | 0x06 | Display brightness |
| 31 | 0x0B | Area / location (weather) |
| 32 | 0x0C | Night/sleep **mode** |
| 33 | 0x0D | Night/sleep **time** window |
| 34 | 0x0E | Night brightness / light level |
| 35 | 0x0F | Device name (payload gets a length-prefix byte) |
| 36 | 0x10 | Read settings (request) |
| 40 | 0x30 | Weather settings |
| 41 | 0x16 | Read weather settings (request) |
| 44 | 0x31 | Week-day language |
| 0  | 0x15 | Wi‑Fi/AP provisioning (JSON `{ssid,pwd}`) |

### Payload semantics (from the Activities)

| Command | Logical id | Payload bytes | Notes |
|---|---|---|---|
| Key tone        | 1  | `[0\|1]`                       | 1 = on, 0 = off |
| Hour format     | 2  | `[0\|1]`                       | 0 = 12h, 1 = 24h |
| Date format     | 3  | `[0\|1]`                       | 0 = month/day, 1 = day/month |
| Temp unit       | 4  | `[0\|1]`                       | **0 = °F, 1 = °C** (confirmed on hardware) |
| Brightness      | 6  | `[0..100]`                     | percent |
| Sleep/night mode| 32 | `[mode]` (`0`/`1`)             | from SleepMode/Waiting screens |
| Sleep/night time| 33 | `[startH, startM, endH, endM]` | 24h values |
| Light level     | 34 | `[level]`                      | LightActivity |
| Week language   | 44 | `[index]`                      | language list index |
| Location/area   | 31 | `z.d.b("<name>(<lat>,<lon>)(<accuKey>)")` | see below |
| Device name     | 35 | UTF‑8 name (len byte auto-added) | |
| Weather/server  | 40 | `[flags, server, 0, 0]` (`z.d.a`) | flags bit0=`rollScreen`=**"two-day weather" toggle**, bit1=`todayWeather` (no UI, keep 0); `server`: see the table below (255=Auto) |
| Read settings   | 36 | `[0]`                          | mirror replies with current settings (see §parser) |
| Read weather    | 41 | `[0]`                          | reply: `[flags, server,0,0,0,len, location]` |

#### Location payload (`z.d.b`)
`z.d.b(bytes)` prepends a 2-byte big-endian length to a UTF‑8 string of the form:
```
"<URL-encoded city name>(<latitude>,<longitude>)(<accuweather location key or empty>)"
e.g.  Madrid(40.4168,-3.7038)(308526)
```
So the opcode-0x0B payload = `[lenHi, lenLo, <those UTF-8 bytes>]`.

#### Weather server values (confirmed on hardware)
The `server` byte in the `0x30` command selects the weather data source. Raw value → app label:

| raw | app label |
|-----|-----------|
| 255 | Auto |
| 1   | No1 |
| 2   | No2 |
| 3   | No3 |
| 0   | No4 |
| 4   | No5 |

TODO (future): map No1–No5 to the actual upstream weather providers. AdGuard DNS observed the
mirror querying `api.accuweather.com`, `api.caiyunapp.com`, and `api.open-meteo.com` while cycling
sources — so No1–No5 correspond to specific providers (and Auto likely tries several). Exact
raw→provider mapping not yet pinned down; would need DNS timestamps aligned to each `server` set.

---

## 3. Quick reference for HomeAssistant
- **Read indoor temp/humidity:** UDP broadcast probe (section 1). Cheap, connectionless, pollable.
- **Change a setting:** UDP datagram to `mirror_ip:8001`, one frame (section 2).
- The mirror IP can change via DHCP — rediscover, or give it a DHCP reservation.
- See `wisemirror.py` for a working implementation of both.
