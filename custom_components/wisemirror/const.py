"""Constants for the WiseMirror integration."""

from __future__ import annotations

DOMAIN = "wisemirror"

# Global (integration-wide) poll interval, persisted in a Store shared by all mirrors.
CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL_SECONDS = 60
MIN_SCAN_INTERVAL_SECONDS = 10
MAX_SCAN_INTERVAL_SECONDS = 3600
GLOBAL_DATA_KEY = f"{DOMAIN}_global"
STORAGE_KEY = f"{DOMAIN}.global_config"
STORAGE_VERSION = 1

CONF_HOST = "host"
CONF_BSSID = "bssid"
CONF_MODEL = "model"

# option: keep the mirror's weather location in sync with HA's home location
CONF_USE_HA_LOCATION = "use_ha_location"
DEFAULT_USE_HA_LOCATION = True

MANUFACTURER = "WiseMirror"

SERVICE_SET_LOCATION = "set_location"
ATTR_LATITUDE = "latitude"
ATTR_LONGITUDE = "longitude"
ATTR_LOCATION_NAME = "name"
