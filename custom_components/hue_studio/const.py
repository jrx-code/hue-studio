"""Constants of the Hue Studio integration."""

DOMAIN = "hue_studio"

CONF_URL = "url"
DEFAULT_URL = "http://hue-web.local:8000"   # placeholder: the form asks for the real address

SCAN_INTERVAL = 60        # seconds between reads of every bridge state (the main bridge answers ~550 kB in ~1.5 s)
CAPACITY_EVERY = 300      # seconds between reads of the scene capacity of a bridge
STREAM_SCAN_INTERVAL = 300  # seconds between state reads while every bridge event stream is up
HUB_SCAN_INTERVAL = 60    # seconds between reads of the hub scenes (a small list)

PLATFORMS = ["binary_sensor", "number", "scene", "select", "sensor", "switch"]
CORE_HUE = "hue"          # the core integration: its devices carry (hue, device rid) and the bridge (hue, bridge_id)
HUB_DEVICE = "hue_web"    # identifier of the device that holds what spans the bridges (hub scenes, reachability)
