"""Constantes para la integración Spock EMS Marstek."""

DOMAIN = "spock_ems_marstek"

# --- API ---
# CAMBIO: Unificamos todo en un solo endpoint
# Ya no se usa API_URL_FETCHER
API_ENDPOINT = "https://flex.spock.es/api/ems_marstek"

# --- Constantes de Configuración ---
CONF_API_TOKEN = "api_token"
CONF_PLANT_ID = "plant_id"
CONF_MARSTEK_IP = "marstek_ip"
CONF_MARSTEK_PORT = "marstek_port"

# --- Defaults ---
DEFAULT_MARSTEK_PORT = 30000
DEFAULT_SCAN_INTERVAL_S = 30
