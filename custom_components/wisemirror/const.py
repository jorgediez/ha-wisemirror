"""Constants for the WiseMirror integration."""

from __future__ import annotations

DOMAIN = "wisemirror"

# option: how often this mirror is polled.
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL_SECONDS = 60
MIN_SCAN_INTERVAL_SECONDS = 10
MAX_SCAN_INTERVAL_SECONDS = 3600
# Where releases up to 1.2.0 kept one poll interval shared by all mirrors: moved
# into each mirror's options at startup, then deleted.
LEGACY_STORAGE_KEY = f"{DOMAIN}.global_config"
LEGACY_STORAGE_VERSION = 1

CONF_HOST = "host"
CONF_BSSID = "bssid"
CONF_MODEL = "model"

# option: keep the mirror's weather location in sync with HA's home location.
# Off unless the user turns it on: nothing is written to a mirror unasked, and the
# city picked in the WiseMirror app stays until then.
CONF_USE_HA_LOCATION = "use_ha_location"
DEFAULT_USE_HA_LOCATION = False

MANUFACTURER = "WiseMirror"

SERVICE_SET_LOCATION = "set_location"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_LOCATION_NAME = "name"
