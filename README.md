# WiseMirror for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)
[![Validate](https://github.com/jorgediez/ha-wisemirror/actions/workflows/validate.yml/badge.svg)](https://github.com/jorgediez/ha-wisemirror/actions/workflows/validate.yml)
[![Tests](https://github.com/jorgediez/ha-wisemirror/actions/workflows/tests.yml/badge.svg)](https://github.com/jorgediez/ha-wisemirror/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Local control of the **weather-station display** built into smart bathroom mirrors that are managed
with the **WiseMirror** mobile app (sold under brands such as **Alasta**, **BYECOLD** or **GS**).

Fully local: no cloud account, no internet connection needed. Home Assistant talks to each
mirror directly over UDP on your LAN.

<img src="custom_components/wisemirror/brand/icon.png" alt="WiseMirror icon" width="96">

## Features

- **Automatic discovery** of mirrors on your network, or add one by IP address.
- **Indoor temperature and humidity** sensors from the mirror's built-in sensors.
- **Display brightness** (raw 0–100, below the app's Low/Medium/High presets) and **night brightness**.
- **Night mode** on/off with start and end times.
- **Clock and date** format (12/24-hour, day-month order), **temperature unit**, **two-day forecast**,
  **weather source**.
- **Weather location**, which can automatically follow Home Assistant's home location.
- Detects **IP address changes** and finds the mirror again by its MAC address.
- **Diagnostics** download, with sensitive data (IP, MAC, location) redacted.
- English and Spanish translations.

## Compatibility

| Brand | Model (as reported by the mirror) | Status |
|---|---|---|
| Alasta | `2M09`, firmware `V1.9.250215` | ✅ Tested |
| BYECOLD, GS, and other mirrors set up with the WiseMirror app | `8J11`, `8J12`, `2K02`, `2M09` | ❔ Should work, not tested |

If your mirror is set up with the **WiseMirror** app, it very likely speaks the same protocol. Please
[report whether it works](https://github.com/jorgediez/ha-wisemirror/issues/new?template=device_report.yml),
including any partial results. Feedback is very welcome!

Some features depend on the hardware: models without a humidity sensor won't get a humidity
entity, and the key tone switch is disabled by default because not all models support it.

## Prerequisites

- The mirror must **already be connected to your 2.4 GHz Wi-Fi**. This integration does not do the
  first-time Wi-Fi setup. Do that once with the official WiseMirror app
  ([iOS](https://apps.apple.com/us/app/wisemirror/id1397701137); on Android search the Play Store
  for "WiseMirror", package `com.smartteam.smartmirror`). After that the app isn't needed anymore.
- Home Assistant and the mirror must be on the **same network segment (L2/VLAN)**. Discovery uses
  a UDP broadcast to port `8000`, and control uses UDP port `8001` on the mirror.
- A **DHCP reservation** for the mirror is recommended. If its IP changes anyway, the integration
  will find it again by its MAC address.
- Home Assistant **2025.1** or newer. The integration icon is shown from 2026.3 onwards.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=jorgediez&repository=ha-wisemirror&category=integration)

Or manually in HACS:

1. Open HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/jorgediez/ha-wisemirror` with type **Integration**.
3. Search for **WiseMirror**, download it, and **restart Home Assistant**.

### Manual

1. Download the [latest release](https://github.com/jorgediez/ha-wisemirror/releases) (or this
   repository) and copy `custom_components/wisemirror` to `<config>/custom_components/wisemirror`.
2. Restart Home Assistant.

## Configuration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wisemirror)

**Settings → Devices & services → Add integration → WiseMirror.**

The integration scans your network and lists the mirrors it finds. Pick one, or choose **Enter IP
address manually**. Repeat this for each mirror; each one becomes its own device.

### Options

Open **Configure** on any mirror:

| Option | Scope | Default | Description |
|---|---|---|---|
| Poll interval | All mirrors | 60 s | How often mirrors are polled for changes made elsewhere (app, buttons). 10–3600 s. Each poll is just a few small UDP packets. |
| Follow Home Assistant's home location | This mirror | On | Keeps the mirror's weather location in sync with Home Assistant's home location (Settings → System → General). |

## Entities

| Platform | Entity | Notes |
|---|---|---|
| Binary sensor | Connectivity | Online/offline. Stays available when the mirror is unreachable, so you can use it in automations. Diagnostic. |
| Sensor | Indoor temperature | °C from the mirror (HA converts it to your unit system). |
| Sensor | Indoor humidity | Only created on models with a humidity sensor. |
| Sensor | Weather location | Diagnostic. |
| Sensor | IP address | Diagnostic, disabled by default. |
| Number | Display brightness | 0–100. |
| Number | Night brightness | 0–100, used while night mode is active. |
| Switch | Night mode | Enables the mirror's built-in night schedule. |
| Switch | Two-day weather | Shows a two-day forecast. |
| Switch | 24-hour clock | Configuration. |
| Switch | Day-month date order | Configuration. |
| Switch | Key tone | Configuration, disabled by default (not supported by all models). |
| Select | Temperature unit | Celsius / Fahrenheit, as shown on the mirror. |
| Select | Weather source | Auto, No1–No5, the same labels as in the app. |
| Time | Night mode start / end | The night-mode window. |

All other entities become *unavailable* while the mirror can't be reached. Every change is
confirmed by the mirror; if it doesn't acknowledge a command, you get an error in the UI.

## Actions

### `wisemirror.set_location`

Sets the weather location manually. Target one or more mirror devices.

```yaml
action: wisemirror.set_location
target:
  device_id: <your mirror device>
data:
  name: León
  latitude: 42.6028912
  longitude: -5.5580577
```

If **Follow Home Assistant's home location** is on, a manual location will be overwritten the next
time Home Assistant's home location changes. Turn the option off to manage the location yourself.

## Tips

### Night mode vs. Home Assistant automations

The mirror's built-in night mode (the *Night mode* switch, start/end times and *Night brightness*)
runs on the mirror itself, with a single fixed window.

For more flexibility, **turn the mirror's night mode off** and drive *Display brightness* from
automations instead: based on sun elevation, presence, weekdays vs. weekends, and so on. Don't use
both at once; two schedulers would fight over the brightness.

```yaml
automation:
  - alias: Dim the mirror at night
    triggers:
      - trigger: sun
        event: sunset
    actions:
      - action: number.set_value
        target:
          entity_id: number.wisemirror_2m09_ceb8_display_brightness
        data:
          value: 5
```

## Troubleshooting

- **Mirror not discovered**: make sure Home Assistant is on the same VLAN/subnet as the mirror and
  that UDP broadcasts aren't filtered (some mesh/guest networks isolate clients). Try adding it
  by IP.
- **"Could not reach a mirror at that address"**: check the IP and that UDP ports `8000` and
  `8001` on the mirror are reachable from Home Assistant.
- **Debug logging**: add this to `configuration.yaml` and restart:

  ```yaml
  logger:
    logs:
      custom_components.wisemirror: debug
  ```

- **Diagnostics**: Settings → Devices & services → WiseMirror → ⋮ → *Download diagnostics*.
  Please attach it to bug reports.

## How it works

The mirror listens on UDP. Home Assistant sends a broadcast probe to discover mirrors and read the
indoor temperature/humidity, and sends small framed commands to read and change settings. The
protocol was reverse-engineered from the WiseMirror app and is documented in
[docs/PROTOCOL.md](docs/PROTOCOL.md). A standalone command-line tool for experimenting is in
[tools/wisemirror.py](tools/wisemirror.py).

## Contributing

Issues and pull requests are welcome. Compatibility reports for other brands/models are especially
useful.

```bash
pip install -r requirements_test.txt
ruff check . && ruff format --check .
pytest
```

The Home Assistant test harness requires Linux or macOS (on Windows, use WSL or the GitHub Actions
results).

## Disclaimer

This is an unofficial, community project. It is not affiliated with or endorsed by the makers of the
WiseMirror app, Alasta, BYECOLD, GS or any other brand. All trademarks belong to their respective
owners. Use at your own risk.

## License

[MIT](LICENSE) © 2026 Jorge Diez
