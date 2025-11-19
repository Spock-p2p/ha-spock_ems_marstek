"""Constantes para la integración Spock EMS Marstek."""

DOMAIN = "spock_ems_marstek"

# --- API ---
API_ENDPOINT = "https://ems-ha.spock.es/api/ems_marstek"

# --- Constantes de Configuración ---
CONF_API_TOKEN = "api_token"
CONF_PLANT_ID = "plant_id"
CONF_MARSTEK_IP = "marstek_ip"
CONF_MARSTEK_PORT = "marstek_port"

# --- Plataformas ---
PLATFORMS: list[str] = ["switch", "sensor"]


# --- Defaults ---
DEFAULT_MARSTEK_PORT = 30000
DEFAULT_SCAN_INTERVAL_S = 60
