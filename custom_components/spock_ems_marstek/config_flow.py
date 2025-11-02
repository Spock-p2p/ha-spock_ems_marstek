"""Config flow para Spock EMS Marstek."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from aiohttp import ClientError

from homeassistant.core import HomeAssistant, callback
from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_PLANT_ID,
    CONF_MODBUS_IP,
    CONF_MODBUS_PORT,
    DEFAULT_MODBUS_PORT,
    API_URL_EMS, # Usamos el endpoint GET para validar el token
)

_LOGGER = logging.getLogger(__name__)

# --- Esquema de datos principal ---
STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): str,
        vol.Required(CONF_PLANT_ID): int,
        vol.Required(CONF_MODBUS_IP): str,
        vol.Required(CONF_MODBUS_PORT, default=DEFAULT_MODBUS_PORT): int,
    }
)


async def validate_auth(
    hass: HomeAssistant, api_token: str
) -> dict[str, str]:
    """Valida el API token haciendo una llamada al endpoint EMS GET."""
    session = async_get_clientsession(hass)
    headers = {"X-Auth-Token": api_token}
    
    try:
        async with session.get(API_URL_EMS, headers=headers, timeout=10) as resp:
            if resp.status == 403:
                return {"base": "invalid_auth"}
            resp.raise_for_status() # Lanza error para otros 4xx/5xx
            return {} # Éxito
            
    except (asyncio.TimeoutError, ClientError):
        return {"base": "cannot_connect"}
    except Exception:
        return {"base": "unknown"}


class SpockEmsMarstekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Maneja el flujo de configuración para Spock EMS Marstek."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Maneja el paso de configuración inicial (usuario)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            
            # Validar el API Token
            errors = await validate_auth(self.hass, user_input[CONF_API_TOKEN])
            
            if not errors:
                # El título único será el Plant ID
                await self.async_set_unique_id(str(user_input[CONF_PLANT_ID]))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Spock EMS (Plant {user_input[CONF_PLANT_ID]})",
                    data=user_input,
                )

        # Muestra el formulario
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlowHandler:
        """Obtiene el flujo de opciones para esta entrada."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(OptionsFlow):
    """Maneja el flujo de opciones (reconfiguración)."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Inicializa el flujo de opciones."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Maneja el paso inicial del flujo de opciones."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            # Validar el token si ha cambiado
            new_token = user_input[CONF_API_TOKEN]
            old_token = self.config_entry.options.get(CONF_API_TOKEN, self.config_entry.data[CONF_API_TOKEN])
            
            if new_token != old_token:
                errors = await validate_auth(self.hass, new_token)
            
            if not errors:
                # Actualiza la configuración de la entrada
                # (Opciones se fusionan sobre los datos)
                return self.async_create_entry(title="", data=user_input)

        # Rellena el formulario con los valores actuales
        options_schema = vol.Schema(
            {
                vol.Required(
                    CONF_API_TOKEN,
                    default=self.config_entry.options.get(
                        CONF_API_TOKEN, self.config_entry.data[CONF_API_TOKEN]
                    ),
                ): str,
                vol.Required(
                    CONF_PLANT_ID,
                    default=self.config_entry.options.get(
                        CONF_PLANT_ID, self.config_entry.data[CONF_PLANT_ID]
                    ),
                ): int,
                vol.Required(
                    CONF_MODBUS_IP,
                    default=self.config_entry.options.get(
                        CONF_MODBUS_IP, self.config_entry.data[CONF_MODBUS_IP]
                    ),
                ): str,
                vol.Required(
                    CONF_MODBUS_PORT,
                    default=self.config_entry.options.get(
                        CONF_MODBUS_PORT, self.config_entry.data[CONF_MODBUS_PORT]
                    ),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )

