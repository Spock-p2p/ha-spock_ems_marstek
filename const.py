"""Constantes para la integración Spock EMS Marstek."""
from __future__ import annotations
from datetime import timedelta

DOMAIN = "spock_ems_marstek"

# Intervalo de sondeo hardcoded
COORDINATOR_UPDATE_INTERVAL = timedelta(seconds=30)

# --- Claves de Configuración ---
CONF_API_TOKEN = "api_token"
CONF_PLANT_ID = "plant_id"
CONF_MODBUS_IP = "modbus_ip"
CONF_MODBUS_PORT = "modbus_port"

DEFAULT_MODBUS_PORT = 30000

# --- Endpoints de API ---
API_URL_FETCHER = "https://flex.spock.es/api/fetcher_marstek"
API_URL_EMS = "https://flex.spock.es/api/ems_marstek"
