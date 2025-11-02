"""El componente de integración Spock EMS para Marstek."""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    COORDINATOR_UPDATE_INTERVAL,
    CONF_API_TOKEN,
    CONF_PLANT_ID,
    CONF_MODBUS_IP,
    CONF_MODBUS_PORT,
    API_URL_FETCHER,
    API_URL_EMS,
)

_LOGGER = logging.getLogger(__name__)

# Este módulo no crea entidades (sensores, etc.), solo sondea y (en el futuro) actuará.
PLATFORMS: list[str] = []


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entrada de configuración cuando las opciones cambian."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura Spock EMS Marstek desde una entrada de configuración."""
    
    # Crea el coordinador
    coordinator = SpockEmsMarstekCoordinator(hass, entry)

    # Almacena el coordinador para que esta entrada lo use
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Listener para recargar si las opciones (ej. IP, Puerto) cambian
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    # Inicia el primer refresco de datos. El coordinador gestionará los siguientes.
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("Spock EMS Marstek: Primer sondeo de API realizado.")

    # Configura las plataformas (ninguna por ahora)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga una entrada de configuración."""
    
    # Descarga plataformas
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Elimina el coordinador de hass.data
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class SpockEmsMarstekCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """
    Coordinador que gestiona el sondeo a los endpoints de Spock EMS.

    Ejecuta dos tareas en cada ciclo:
    1. POST a /api/fetcher_marstek (para enviar telemetría)
    2. GET a /api/ems_marstek (para recibir comandos)
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Inicializa el coordinador."""
        self.config = {**entry.data, **entry.options}
        self.api_token: str = self.config[CONF_API_TOKEN]
        self.plant_id: int = self.config[CONF_PLANT_ID]
        self.modbus_ip: str = self.config[CONF_MODBUS_IP]
        self.modbus_port: int = self.config[CONF_MODBUS_PORT]
        
        self._session = async_get_clientsession(hass)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=COORDINATOR_UPDATE_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Función principal de sondeo llamada por el coordinador cada 30s.
        """
        headers = {"X-Auth-Token": self.api_token}
        
        # --- Tarea 1: Enviar telemetría (POST a fetcher_marstek) ---
        try:
            # Prepara el body hardcoded con el plant_id de la config
            fetcher_body = {
                "plant_id": str(self.plant_id), # El ejemplo usa string
                "bat_soc": "34",
                "bat_power": "50",
                "pv_power": "1234",
                "ongrid_power": "560",
                "bat_charge_allowed": "true",
                "bat_discharge_allowed": "true",
                "bat_capacity": "5120",
                "total_grid_output_energy": "800"
            }
            
            _LOGGER.debug("Enviando telemetría (fetcher POST) a %s", API_URL_FETCHER)
            async with self._session.post(
                API_URL_FETCHER, 
                headers=headers, 
                json=fetcher_body
            ) as resp:
                
                if resp.status == 403:
                    _LOGGER.warning("Token API inválido (403) al enviar telemetría.")
                    # No lanzamos UpdateFailed aquí, para permitir que el GET de comandos se intente
                elif resp.status not in (200, 201, 204):
                    txt = await resp.text()
                    _LOGGER.error(
                        "Error en API Fetcher (%s): %s", resp.status, txt
                    )
                else:
                     _LOGGER.debug("Telemetría enviada correctamente.")

        except Exception as err:
            _LOGGER.error("Error al enviar telemetría (fetcher): %s", err)
            # No lanzamos UpdateFailed, para que el siguiente paso se intente

        
        # --- Tarea 2: Recibir comandos (GET a ems_marstek) ---
        try:
            _LOGGER.debug("Solicitando comandos (EMS GET) de %s", API_URL_EMS)
            async with self._session.get(API_URL_EMS, headers=headers) as resp:
                if resp.status == 403:
                    raise UpdateFailed("API Token inválido (403)")
                if resp.status != 200:
                    txt = await resp.text()
                    _LOGGER.error("Error en API EMS (%s): %s", resp.status, txt)
                    raise UpdateFailed(f"Error HTTP {resp.status} al obtener comandos")

                data = await resp.json(content_type=None)

            # Validación mínima de la respuesta
            if not isinstance(data, dict) or "battery_operation" not in data:
                raise UpdateFailed(f"Respuesta inesperada de API EMS: {data}")

            _LOGGER.debug("Comandos EMS recibidos: %s", data)

            # --- Lógica futura ---
            await self._execute_modbus_actions(data)
            
            # Devolvemos los datos de comandos (para futuro sensor, si se añade)
            return data

        except UpdateFailed:
            raise # Re-lanza el error de token/API
        except Exception as err:
            raise UpdateFailed(f"Error al obtener comandos EMS: {err}") from err

    async def _execute_modbus_actions(self, data: dict[str, Any]) -> None:
        """En el futuro, esta función se conectará al inversor Marstek."""
        
        # Extraer acciones del JSON de respuesta 'data'
        operation = data.get("battery_operation")
        action = data.get("battery_action")
        amount = data.get("amount")

        _LOGGER.info(
            "[FUTURO] Se ejecutaría lógica Modbus UDP a %s:%s | Operación: %s, Acción: %s, Cantidad: %s",
            self.modbus_ip,
            self.modbus_port,
            operation,
            action,
            amount
        )
        # Aquí iría la lógica de conexión Modbus (ej. con pymodbus)
        # Por ahora, solo registramos
        await asyncio.sleep(0) # Placeholder para una futura op asíncrona

