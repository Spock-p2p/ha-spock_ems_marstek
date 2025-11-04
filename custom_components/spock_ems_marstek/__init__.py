"""Integración Spock EMS Marstek"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
# CAMBIO: Ya no se necesita async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    API_ENDPOINT,
    CONF_API_TOKEN,
    CONF_PLANT_ID,
    DEFAULT_SCAN_INTERVAL_S,
    PLATFORMS, # <-- CAMBIO: Importamos PLATFORMS
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura la integración desde la entrada de configuración."""
    
    coordinator = SpockEnergyCoordinator(hass, entry) # <-- CAMBIO: Pasamos 'entry'

    # CAMBIO: Guardamos el estado inicial del interruptor
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "is_enabled": True, # Estado inicial del switch (habilitado)
    }

    # Primer fetch
    await asyncio.sleep(2)
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("Spock EMS Marstek: Primer fetch realizado.")

    # CAMBIO: Cargar plataformas (switch.py)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Permitir reconfiguración
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    
    _LOGGER.info(
         "Spock EMS Marstek: Ciclo automático (gestionado por listener) iniciado cada %s.", 
         coordinator.update_interval
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga la entrada de configuración."""
    # Descargar plataformas (switch.py)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # CAMBIO: Limpiar datos (ya no hay 'unsub' que cancelar)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    
    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Recarga la entrada de configuración al modificar opciones."""
    await hass.config_entries.async_reload(entry.entry_id)


class SpockEnergyCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator que gestiona el ciclo de API unificado."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Inicializa el coordinador."""
        self.config_entry = entry # <-- CAMBIO: Guardamos la entry
        self.config = {**entry.data, **entry.options}
        self.api_token: str = self.config[CONF_API_TOKEN]
        self.plant_id: int = self.config[CONF_PLANT_ID]
        self._session = async_get_clientsession(hass)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_S),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Ciclo de actualización unificado.
        Se pausa si el switch está en 'off'.
        """
        
        # --- CAMBIO: Comprobar si el sondeo está habilitado ---
        entry_id = self.config_entry.entry_id
        is_enabled = self.hass.data[DOMAIN].get(entry_id, {}).get("is_enabled", True)
        
        if not is_enabled:
            _LOGGER.debug("Sondeo API deshabilitado por el interruptor. Omitiendo ciclo.")
            # Devolvemos los datos anteriores para que los sensores (futuros)
            # no pierdan su estado.
            return self.data 
        # --- FIN DEL CAMBIO ---

        _LOGGER.debug("Iniciando ciclo de actualización unificado de Spock EMS")
        headers = {"X-Auth-Token": self.api_token}
        
        telemetry_data = {
            "plant_id": str(self.plant_id),
            "bat_soc": "34",
            "bat_power": "50",
            "pv_power": "1234",
            "ongrid_power": "560",
            "bat_charge_allowed": "true",
            "bat_discharge_allowed": "true",
            "bat_capacity": "5120",
            "total_grid_output_energy": "800"
        }
        
        _LOGGER.debug("Enviando telemetría y obteniendo comandos desde %s", API_ENDPOINT)
        
        try:
            async with self._session.post(
                API_ENDPOINT, 
                headers=headers, 
                json=telemetry_data
            ) as resp:
                
                if resp.status == 403:
                    raise UpdateFailed("API Token inválido (403)")
                if resp.status != 200:
                    txt = await resp.text()
                    _LOGGER.error("API error %s: %s", resp.status, txt)
                    raise UpdateFailed(f"Error de API (HTTP {resp.status})")

                data = await resp.json(content_type=None)
                
                if not isinstance(data, dict) or "status" not in data or "operation_mode" not in data:
                    _LOGGER.warning("Formato de respuesta de comandos inesperado: %s", data)
                    raise UpdateFailed(f"Formato de respuesta inesperado: {data}")

                _LOGGER.debug("Comandos recibidos: %s", data)
                
                # TODO: Aquí, en el futuro, se procesarían los comandos
                # self.process_commands(data)
                
                return data

        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error en el ciclo de actualización de Spock EMS: %s", err)
            raise UpdateFailed(f"Error en el ciclo de actualización: {err}") from err
