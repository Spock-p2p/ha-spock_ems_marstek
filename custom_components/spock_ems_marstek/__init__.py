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

        self._local_ip: str | None = None

    # ---- Utils ----
    def _resolve_local_ip_for(self, dst_ip: str) -> str:
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

    def _pick(self, d: dict | None, *keys, default=None):
        if not d:
            return default
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return default

    async def _async_send_udp_command(
        self, payload: dict, timeout: float = 5.0, retry: int = 1
    ) -> dict:
        """
        Envía un comando UDP a Marstek y espera respuesta.
        Requisitos: mismo puerto en origen y destino (marstek_port), misma LAN.
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

                await loop.sock_sendto(sock, command, (self.marstek_ip, self.marstek_port))

                response, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 16384), timeout=timeout
                )
                _LOGGER.debug("UDP RX de %s: %s", addr, response.decode("utf-8"))

                response_data = json.loads(response.decode("utf-8"))
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
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

        raise asyncio.TimeoutError("Sin respuesta tras reintentos")

    # ---- Ciclo ----
    async def _async_update_data(self) -> dict[str, Any]:
        """
        1) Lee telemetría (EM.GetStatus + Bat.GetStatus)
        2) Envía telemetría a Spock
        3) Devuelve comandos/estado de Spock
        """
        entry_id = self.config_entry.entry_id
        is_enabled = self.hass.data[DOMAIN].get(entry_id, {}).get("is_enabled", True)
        if not is_enabled:
            _LOGGER.debug("Sondeo API deshabilitado. Omitiendo ciclo.")
            return self.data

        _LOGGER.debug("Iniciando ciclo de actualización unificado de Spock EMS")

        telemetry_data: dict[str, str] = {}
        em_data: dict[str, Any] | None = None
        bat_data: dict[str, Any] | None = None

        # 1) Lecturas
        try:
            # En tu fw v139, EM.GetStatus devuelve total_power y por fases
            em_payload = {"id": 1, "method": "EM.GetStatus", "params": {"id": 0}}
            em_data = await self._async_send_udp_command(em_payload, timeout=5.0, retry=1)
        except Exception as e:
            _LOGGER.warning("EM.GetStatus falló: %r", e)

        try:
            bat_payload = {"id": 2, "method": "Bat.GetStatus", "params": {"id": 0}}
            bat_data = await self._async_send_udp_command(bat_payload, timeout=5.0, retry=1)
        except Exception as e:
            _LOGGER.warning("Bat.GetStatus falló: %r", e)

        # 2) Mapeo normalizado
        if em_data is None and bat_data is None:
            _LOGGER.warning("No se pudo obtener telemetría de Marstek. Enviando ceros.")
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
            b = bat_data or {}
            e = em_data or {}

            # Batería
            bat_soc      = self._pick(b, "bat_soc", "soc", default=0)
            bat_power    = self._pick(b, "bat_power", "power", "p_bat", default=0)  # muchos FW no lo exponen
            chg_allowed  = bool(self._pick(b, "charg_ag", "charg_flag", default=False))
            dchg_allowed = bool(self._pick(b, "dischrg_ag", "dischrg_flag", default=False))
            bat_cap      = self._pick(b, "bat_capacity", "bat_cap", default=0)
            rated_cap    = self._pick(b, "rated_capacity", default=None)
            bat_capacity = rated_cap if (bat_cap in (0, None) and rated_cap is not None) else bat_cap

            # Energía/red (EM.GetStatus)
            # total_power: potencia total medida en red (signo según pinza/instalación).
            ongrid_power = self._pick(e, "total_power", default=0)
            # pv_power no llega por EM.GetStatus en tu FW; dejamos 0 por ahora.
            pv_power     = 0

            telemetry_data = {
                "plant_id": str(self.plant_id),
                "bat_soc": str(bat_soc),
                "bat_power": str(bat_power or 0),
                "pv_power": str(pv_power),
                "ongrid_power": str(ongrid_power),
                "bat_charge_allowed": str(chg_allowed).lower(),
                "bat_discharge_allowed": str(dchg_allowed).lower(),
                "bat_capacity": str(bat_capacity or 0),
                "total_grid_output_energy": "0",
            }

            _LOGGER.debug("Telemetría real obtenida (normalizada): %s", telemetry_data)

        # 3) POST a Spock
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
                # TODO: Procesar comandos
                return data

        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error en el ciclo de actualización de Spock EMS (API POST): %s", err)
            raise UpdateFailed(f"Error en el ciclo de actualización (API POST): {err}") from err
