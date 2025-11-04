"""Integración Spock EMS Marstek"""
from __future__ import annotations

import asyncio
import logging
import json
import socket
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    API_ENDPOINT,
    CONF_API_TOKEN,
    CONF_PLANT_ID,
    CONF_MARSTEK_IP,
    CONF_MARSTEK_PORT,
    DEFAULT_SCAN_INTERVAL_S,
    PLATFORMS,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura la integración desde la entrada de configuración."""
    
    coordinator = SpockEnergyCoordinator(hass, entry)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "is_enabled": True, 
    }

    await asyncio.sleep(2)
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("Spock EMS Marstek: Primer fetch realizado.")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info(
         "Spock EMS Marstek: Ciclo automático (gestionado por listener) iniciado cada %s.", 
         coordinator.update_interval
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descarga la entrada de configuración."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

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
        self.config_entry = entry
        self.config = {**entry.data, **entry.options}
        self.api_token: str = self.config[CONF_API_TOKEN]
        self.plant_id: int = self.config[CONF_PLANT_ID]
        self.marstek_ip: str = self.config[CONF_MARSTEK_IP]
        self.marstek_port: int = self.config[CONF_MARSTEK_PORT]
        self._session = async_get_clientsession(hass)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_S),
        )

    async def _async_send_udp_command(self, payload: dict, timeout: int = 5) -> dict:
        """Envía un comando UDP al inversor Marstek y espera una respuesta."""
        loop = asyncio.get_running_loop()
        
        # Crear payload
        command = json.dumps(payload).encode('utf-8')
        
        # Crear socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False) # Esencial para asyncio
        
        try:
            _LOGGER.debug(f"Enviando UDP a {self.marstek_ip}:{self.marstek_port}: {command}")
            await loop.sock_sendto(sock, command, (self.marstek_ip, self.marstek_port))
            
            # Esperar respuesta
            response, addr = await asyncio.wait_for(loop.sock_recvfrom(sock, 1024), timeout=timeout)
            
            _LOGGER.debug(f"Recibido UDP de {addr}: {response.decode('utf-8')}")
            
            # Decodificar y parsear
            response_data = json.loads(response.decode('utf-8'))
            
            # Validar respuesta
            if response_data.get("id") != payload.get("id") or "result" not in response_data:
                raise ValueError(f"Respuesta UDP inesperada: {response_data}")
                
            return response_data["result"]
            
        except asyncio.TimeoutError:
            _LOGGER.warning(f"Timeout (5s) esperando respuesta UDP para el comando: {payload.get('method')}")
            raise
        except json.JSONDecodeError:
            _LOGGER.warning(f"Error al decodificar respuesta JSON de Marstek: {response.decode('utf-8')}")
            raise
        except Exception as e:
            _LOGGER.error(f"Error en comunicación UDP: {e}")
            raise
        finally:
            sock.close()


    async def _async_update_data(self) -> dict[str, Any]:
        """
        Ciclo de actualización unificado:
        1. Obtiene telemetría real del inversor (UDP)
        2. Envía telemetría a Spock (POST)
        3. Recibe comandos de Spock (en la respuesta del POST)
        """
        
        entry_id = self.config_entry.entry_id
        is_enabled = self.hass.data[DOMAIN].get(entry_id, {}).get("is_enabled", True)
        
        if not is_enabled:
            _LOGGER.debug("Sondeo API deshabilitado por el interruptor. Omitiendo ciclo.")
            return self.data 

        _LOGGER.debug("Iniciando ciclo de actualización unificado de Spock EMS")

        try:
            # 1. Obtener datos de telemetría del inversor
            
            # Comando 1: ES.GetStatus (Para potencias, SOC, capacidad, energía)
            es_status_payload = {"id": 1, "method": "ES.GetStatus", "params": {"id": 0}}
            es_data = await self._async_send_udp_command(es_status_payload)
            
            # Comando 2: Bat.GetStatus (Para permisos de carga/descarga)
            bat_status_payload = {"id": 2, "method": "Bat.GetStatus", "params": {"id": 0}}
            bat_data = await self._async_send_udp_command(bat_status_payload)

            # 2. Mapear los datos al formato de la API de Spock
            # (Convirtiendo todo a string como en el ejemplo hardcoded)
            telemetry_data = {
                "plant_id": str(self.plant_id),
                "bat_soc": str(es_data.get("bat_soc")),
                "bat_power": str(es_data.get("bat_power")),
                "pv_power": str(es_data.get("pv_power")),
                "ongrid_power": str(es_data.get("ongrid_power")),
                "bat_charge_allowed": str(bat_data.get("charg_ag", False)).lower(),
                "bat_discharge_allowed": str(bat_data.get("dischrg_ag", False)).lower(),
                "bat_capacity": str(es_data.get("bat_cap")), # 'bat_cap' de ES.GetStatus
                "total_grid_output_energy": str(es_data.get("total_grid_output_energy"))
            }
            
        except asyncio.TimeoutError:
            raise UpdateFailed("Timeout al contactar con el inversor Marstek por UDP")
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            _LOGGER.warning(f"Error al procesar datos de Marstek (¿respuesta inesperada?): {e}")
            raise UpdateFailed(f"Error al procesar datos de Marstek: {e}")
        except Exception as e:
            # Errores genéricos de UDP (ej. Connection refused, Network unreachable)
            _LOGGER.error(f"Error de comunicación UDP con Marstek: {e}")
            raise UpdateFailed(f"Error de comunicación con Marstek: {e}")

        # 3. Enviar telemetría y recibir comandos (Lógica de Spock API)
        _LOGGER.debug("Enviando telemetría y obteniendo comandos desde %s", API_ENDPOINT)
        headers = {"X-Auth-Token": self.api_token}
        
        try:
            async with self._session.post(
                API_ENDPOINT, 
                headers=headers, 
                json=telemetry_data # <-- Se usa la telemetría real
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
            _LOGGER.error("Error en el ciclo de actualización de Spock EMS (API POST): %s", err)
            raise UpdateFailed(f"Error en el ciclo de actualización (API POST): {err}") from err
