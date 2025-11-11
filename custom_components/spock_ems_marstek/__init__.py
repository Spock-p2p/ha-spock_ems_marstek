"""Integración Spock EMS Marstek"""
from __future__ import annotations

import asyncio
import logging
import json
import socket
from datetime import timedelta
from typing import Any, Tuple

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

    # Primer refresh para poblar estado
    await asyncio.sleep(2)
    await coordinator.async_config_entry_first_refresh()
    _LOGGER.info("Spock EMS Marstek: Primer fetch realizado.")

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info(
        "Spock EMS Marstek: Ciclo automático iniciado cada %s.",
        coordinator.update_interval,
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
        self.hass = hass
        self.config_entry = entry
        self.config = {**entry.data, **entry.options}
        self.api_token: str = self.config[CONF_API_TOKEN]
        self.plant_id: int = self.config[CONF_PLANT_ID]
        self.marstek_ip: str = self.config[CONF_MARSTEK_IP]
        self.marstek_port: int = int(self.config[CONF_MARSTEK_PORT])
        self._session = async_get_clientsession(hass)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL_S),
        )

        # Cache de IP local resuelta hacia la batería
        self._local_ip: str | None = None

    # ---------- Utilidades UDP específicas de Marstek ----------

    def _resolve_local_ip_for(self, dst_ip: str) -> str:
        """
        Autodetecta la IP local apropiada hacia dst_ip usando un "connect" UDP de mentira.
        """
        if self._local_ip:
            return self._local_ip
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect((dst_ip, 9))  # puerto dummy
            self._local_ip = s.getsockname()[0]
        finally:
            s.close()
        _LOGGER.debug("IP local detectada para %s -> %s", dst_ip, self._local_ip)
        return self._local_ip  # type: ignore[return-value]

    async def _async_send_udp_command(
        self, payload: dict, timeout: float = 5.0, retry: int = 1
    ) -> dict:
        """
        Envía un comando UDP a Marstek y espera una respuesta.
        Requisitos del equipo:
          - Mismo puerto en ORIGEN y DESTINO (marstek_port)
          - Misma LAN
        Estrategia:
          - bind(local_ip, marstek_port)
          - sendto + recvfrom (buffer amplio)
          - valida id y estructura
          - reintenta 1 vez opcionalmente
        """
        loop = asyncio.get_running_loop()
        local_ip = self._resolve_local_ip_for(self.marstek_ip)
        command = json.dumps(payload).encode("utf-8")

        for attempt in range(retry + 1):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            sock.setblocking(False)

            try:
                # Bind estricto a la IP local correcta y al mismo puerto que el destino
                sock.bind((local_ip, self.marstek_port))

                _LOGGER.debug(
                    "UDP %s -> %s:%s (origen %s:%s) payload=%s",
                    local_ip,
                    self.marstek_ip,
                    self.marstek_port,
                    local_ip,
                    self.marstek_port,
                    command,
                )

                await loop.sock_sendto(
                    sock, command, (self.marstek_ip, self.marstek_port)
                )

                # Espera respuesta
                response, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 16384), timeout=timeout
                )

                _LOGGER.debug("UDP RX de %s: %s", addr, response.decode("utf-8"))
                response_data = json.loads(response.decode("utf-8"))

                # Validación básica
                if response_data.get("id") != payload.get("id") or "result" not in response_data:
                    raise ValueError(f"Respuesta UDP inesperada: {response_data}")

                return response_data["result"]

            except asyncio.TimeoutError:
                _LOGGER.warning(
                    "Timeout (%.1fs) esperando UDP para %s (intento %d/%d)",
                    timeout,
                    payload.get("method"),
                    attempt + 1,
                    retry + 1,
                )
                if attempt >= retry:
                    raise
            except json.JSONDecodeError as je:
                _LOGGER.warning(
                    "Respuesta no-JSON de Marstek para %s: %s",
                    payload.get("method"),
                    je,
                )
                raise
            except OSError as ose:
                _LOGGER.error("Error de socket UDP: %s", ose)
                raise
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

        # No debería alcanzarse
        raise asyncio.TimeoutError("Sin respuesta tras reintentos")

    # ---------- Ciclo de actualización ----------

    async def _async_update_data(self) -> dict[str, Any]:
        """
        Ciclo de actualización unificado:
        1) Lee telemetría por UDP (ES.GetStatus + Bat.GetStatus)
        2) Envía telemetría a Spock (POST)
        3) Devuelve comandos/estado de Spock
        """
        entry_id = self.config_entry.entry_id
        is_enabled = self.hass.data[DOMAIN].get(entry_id, {}).get("is_enabled", True)
        if not is_enabled:
            _LOGGER.debug("Sondeo API deshabilitado por el interruptor. Omitiendo ciclo.")
            return self.data

        _LOGGER.debug("Iniciando ciclo de actualización unificado de Spock EMS")

        telemetry_data: dict[str, str] = {}

        # 1) Lectura UDP (intentamos ambos; si uno falla seguimos con el otro)
        es_data: dict[str, Any] | None = None
        bat_data: dict[str, Any] | None = None

        try:
            es_status_payload = {"id": 1, "method": "ES.GetStatus", "params": {"id": 0}}
            es_data = await self._async_send_udp_command(es_status_payload, timeout=5.0, retry=1)
        except Exception as e:
            _LOGGER.warning("ES.GetStatus falló: %s", e)

        try:
            bat_status_payload = {"id": 2, "method": "Bat.GetStatus", "params": {"id": 0}}
            bat_data = await self._async_send_udp_command(bat_status_payload, timeout=5.0, retry=1)
        except Exception as e:
            _LOGGER.warning("Bat.GetStatus falló: %s", e)

        if es_data is None and bat_data is None:
            _LOGGER.warning("No se pudo obtener telemetría de Marstek (ambos métodos fallaron). Enviando ceros.")
            telemetry_data = {
                "plant_id": str(self.plant_id),
                "bat_soc": "0",
                "bat_power": "0",
                "pv_power": "0",
                "ongrid_power": "0",
                "bat_charge_allowed": "false",
                "bat_discharge_allowed": "false",
                "bat_capacity": "0",
                "total_grid_output_energy": "0",
            }
        else:
            # 2) Mapear datos reales con preferencia por la fuente correcta
            #    - Batería: Bat.GetStatus
            #    - PV / red / carga: ES.GetStatus
            telemetry_data = {
                "plant_id": str(self.plant_id),
                "bat_soc": str((bat_data or {}).get("bat_soc") or (es_data or {}).get("bat_soc") or 0),
                "bat_power": str((bat_data or {}).get("bat_power") or (es_data or {}).get("bat_power") or 0),
                "pv_power": str((es_data or {}).get("pv_power") or 0),
                "ongrid_power": str((es_data or {}).get("ongrid_power") or (es_data or {}).get("grid_power") or 0),
                "bat_charge_allowed": str((bat_data or {}).get("charg_ag", False)).lower(),
                "bat_discharge_allowed": str((bat_data or {}).get("dischrg_ag", False)).lower(),
                "bat_capacity": str((bat_data or {}).get("bat_cap") or (es_data or {}).get("bat_cap") or 0),
                "total_grid_output_energy": str((es_data or {}).get("total_grid_output_energy") or 0),
            }
            _LOGGER.debug("Telemetría real obtenida: %s", telemetry_data)

        # 3) Enviar telemetría y recibir comandos (Spock API)
        _LOGGER.debug("Enviando telemetría a Spock API: %s", telemetry_data)
        headers = {"X-Auth-Token": self.api_token}

        try:
            async with self._session.post(
                API_ENDPOINT,
                headers=headers,
                json=telemetry_data,
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
                # TODO: Procesar comandos recibidos en 'data'
                return data

        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error en el ciclo de actualización de Spock EMS (API POST): %s", err)
            raise UpdateFailed(f"Error en el ciclo de actualización (API POST): {err}") from err
