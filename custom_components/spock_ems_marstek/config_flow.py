"""Config flow para Spock EMS Marstek."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, callback # <--- ¡AÑADIDO!
from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_PLANT_ID,
    CONF_MARSTEK_IP,
    CONF_MARSTEK_PORT,
    DEFAULT_MARSTEK_PORT,
    API_ENDPOINT,
)

_LOGGER = logging.getLogger(__name__)


async def validate_auth(
    hass: HomeAssistant, api_token: str
) -> dict[str, str]:
    """Valida el API token haciendo una llamada simple."""
    session = async_get_clientsession(hass)
    headers = {"X-Auth-Token": api_token}
    
    try:

        # Por ahora, asumimos que un POST (aunque falle por datos) valida el 403
        async with session.post(API_ENDPOINT, headers=headers, timeout=10) as resp:
            if resp.status == 403:
                return {"base": "invalid_auth"}
            # No esperamos 200 OK necesariamente si el body está mal
            # pero si no es 403, el token es probablemente bueno.
            return {} # Éxito
            
    except Exception:
        _LOGGER.exception("No se pudo conectar al validar API token")
        return {"base": "cannot_connect"}


class SpockEmsMarstekConfigFlow(ConfigFlow, domain=DOMAIN):
    """Maneja el flujo de configuración."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Paso inicial de configuración."""
        errors: dict[str, str] = {}
        if user_input is not None:
            
            errors = await validate_auth(self.hass, user_input[CONF_API_TOKEN])
            
            if not errors:
                await self.async_set_unique_id(str(user_input[CONF_PLANT_ID]))
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Spock EMS (Planta {user_input[CONF_PLANT_ID]})",
                    data=user_input,
                )

        STEP_USER_DATA_SCHEMA = vol.Schema(
            {
                vol.Required(CONF_API_TOKEN): str,
                vol.Required(CONF_PLANT_ID): int,
                vol.Required(CONF_MARSTEK_IP): str,
                vol.Optional(
                    CONF_MARSTEK_PORT, default=DEFAULT_MARSTEK_PORT
                ): int,
            }
        )

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
        """Inicializa."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Maneja el paso inicial del flujo de opciones."""
        errors: dict[str, str] = {}
        
        if user_input is not None:
            old_token = self.config_entry.options.get(CONF_API_TOKEN, self.config_entry.data[CONF_API_TOKEN])
            
            if user_input[CONF_API_TOKEN] != old_token:
                errors = await validate_auth(self.hass, user_input[CONF_API_TOKEN])
            
            if not errors:
                return self.async_create_entry(title="", data=user_input)

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
                    CONF_MARSTEK_IP,
                    default=self.config_entry.options.get(
                        CONF_MARSTEK_IP, self.config_entry.data[CONF_MARSTEK_IP]
                    ),
                ): str,
                vol.Optional(
                    CONF_MARSTEK_PORT,
                    default=self.config_entry.options.get(
                        CONF_MARSTEK_PORT, self.config_entry.data.get(CONF_MARSTEK_PORT, DEFAULT_MARSTEK_PORT)
                    ),
                ): int,
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=options_schema, errors=errors
        )
