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
from homeassistant.util import dt as dt_util

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
        self._last_cmd_fingerprint: str | None = None  # por si quieres deduplicar órdenes

    # ---- Utils ----
    def _resolve_local_ip_for(self, dst_ip: str) -> str:
        """Autodetecta la IP local adecuada hacia dst_ip."""
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
        """Devuelve el primer valor existente en d de entre keys."""
        if not d:
            return default
        for k in keys:
            if k in d and d[k] is not None:
                return d[k]
        return default

    def _week_set_for_today(self) -> int:
        """Máscara week_set para el día actual (L=1, M=2, X=4, J=8, V=16, S=32, D=64)."""
        now = dt_util.now()
        return 1 << now.weekday()

    def _default_time_window(self) -> tuple[str, str]:
        """
        Ventana por defecto:
        - start_time: HH:00 (hora actual redondeada hacia abajo)
        - end_time: start_time + 1h
        """
        now = dt_util.now()
        start = now.replace(minute=0, second=0, microsecond=0)
        end = start + timedelta(hours=1)
        return (start.strftime("%H:%M"), end.strftime("%H:%M"))

    def _weekset_human(self, mask: int) -> str:
        """Texto humano para week_set (p.ej. 'lunes', 'lunes, martes', 'todos los días')."""
        if mask == 127:
            return "todos los días"
        nombres = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
        activos = [nombres[i] for i in range(7) if mask & (1 << i)]
        if not activos:
            return "sin días"
        if len(activos) == 1:
            return activos[0]
        return ", ".join(activos)

    def _str_or_none(self, value) -> str | None:
        """Devuelve str(valor) o None si valor es None."""
        if value is None:
            return None
        return str(value)

    def _bool_str_or_none(self, value) -> str | None:
        """Devuelve 'true'/'false' o None si value es None."""
        if value is None:
            return None
        return str(bool(value)).lower()

    async def _async_send_udp_command(
        self, payload: dict, timeout: float = 5.0, retry: int = 3
    ) -> dict:
        """
        Envía un comando UDP a Marstek y espera respuesta.
        Requisitos: mismo puerto en origen y destino (marstek_port), misma LAN.
        'retry' = reintentos adicionales (total intentos = retry + 1).
        """
        loop = asyncio.get_running_loop()
        local_ip = self._resolve_local_ip_for(self.marstek_ip)

        # Serialización MINIFICADA (como tu script) para evitar parseos raros
        command = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        _LOGGER.debug("TX bytes → %r", command)

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
                    "UDP %s -> %s:%s (origen %s:%s)",
                    local_ip,
                    self.marstek_ip,
                    self.marstek_port,
                    local_ip,
                    self.marstek_port,
                )

                await loop.sock_sendto(sock, command, (self.marstek_ip, self.marstek_port))

                response, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 16384), timeout=timeout
                )
                _LOGGER.debug("UDP RX de %s: %s", addr, response.decode("utf-8"))

                response_data = json.loads(response.decode("utf-8"))
                # Aceptamos tanto 'result' como 'error'; si viene 'error', levantamos excepción
                if "error" in response_data:
                    raise ValueError(f"Respuesta de error: {response_data}")
                if response_data.get("id") != payload.get("id") or "result" not in response_data:
                    raise ValueError(f"Respuesta UDP inesperada: {response_data}")
                return response_data["result"]

            except asyncio.TimeoutError:
                is_final = attempt >= retry
                log_fn = _LOGGER.warning if is_final else _LOGGER.debug
                log_fn(
                    "Timeout (%.1fs) esperando UDP para %s (intento %d/%d)",
                    timeout,
                    payload.get("method", "UNKNOWN"),
                    attempt + 1,
                    retry + 1,
                )
                if is_final:
                    raise
            finally:
                try:
                    sock.close()
                except Exception:
                    pass

        raise asyncio.TimeoutError("Sin respuesta tras reintentos")

    # ---- Construcción y envío de órdenes ----
    def _build_manual_cfg(
        self,
        power: int,
        start_time: str,
        end_time: str,
        week_set: int,
        enable: int = 1,
        time_num: int = 6,
    ) -> dict:
        """
        Construye el bloque manual_cfg para ES.SetMode en modo Manual.
        - power: vatios (+carga / -descarga)
        - start_time/end_time: "HH:MM"
        - week_set: máscara de días (L=1, M=2, ..., D=64)
        - enable: 1 aplica el tramo
        - time_num: índice del tramo (fijo 6)
        """
        return {
            "time_num": time_num,
            "start_time": start_time,
            "end_time": end_time,
            "week_set": int(week_set),
            "power": int(power),
            "enable": int(enable),
        }

    async def _apply_spock_command(self, spock: dict[str, Any]) -> None:
        """
        Aplica la orden recibida desde Spock (ENVÍO ACTIVO):
        - operation_mode: 'none' | 'charge' | 'discharge' | 'auto'
        - action: magnitud en W (siempre positiva en la API Spock) [solo charge/discharge]
        - start_time/end_time/day (opcionales). Si no están, se usan los defaults.
        """
        op_mode = (spock.get("operation_mode") or "none").lower()

        # --- Modo NONE: no hacer nada ---
        if op_mode == "none":
            _LOGGER.debug("Spock: operation_mode=none. No se envía orden a Marstek.")
            self._last_cmd_fingerprint = None
            return

        # --- Modo AUTO -> ES.SetMode Auto con auto_cfg.enable=1 ---
        if op_mode == "auto":
            payload = {
                "id": 1,
                "method": "ES.SetMode",
                "params": {
                    "id": 1,
                    "config": {
                        "mode": "Auto",
                        "auto_cfg": {
                            "enable": 1,
                        },
                    },
                },
            }

            _LOGGER.debug("Spock: operation_mode=auto. Activando modo Auto en Marstek.")
            _LOGGER.debug("ES.SetMode (Auto) payload: %s", json.dumps(payload, ensure_ascii=False))

            fp = json.dumps(payload, sort_keys=True)
            try:
                result = await self._async_send_udp_command(payload, timeout=5.0, retry=3)
                _LOGGER.debug("Respuesta ES.SetMode (Auto): %s", result)
                self._last_cmd_fingerprint = fp
            except Exception as e:
                _LOGGER.error("Fallo enviando ES.SetMode Auto a Marstek: %s", e)
            return

        # --- Resto: charge / discharge (comportamiento EXISTENTE) ---

        # Magnitud de potencia (W) en absoluto
        raw_action = spock.get("action", 0)
        try:
            mag = int(float(raw_action))
        except Exception:
            mag = 0
        if mag < 0:
            mag = -mag

        # ⚠️ Signo invertido según observación del equipo:
        # - 'charge' recibido implica CARGA real → power negativo
        # - 'discharge' recibido implica DESCARGA real → power positivo
        if op_mode == "charge":
            power = -mag
        elif op_mode == "discharge":
            power = +mag
        else:
            _LOGGER.warning("Spock: operation_mode desconocido: %r. Ignorando.", op_mode)
            return

        # Ventana horaria / week_set (del payload o por defecto)
        start_time = spock.get("start_time")
        end_time = spock.get("end_time")
        if not (start_time and end_time):
            start_time, end_time = self._default_time_window()

        day_val = spock.get("day", None)
        try:
            week_set = int(day_val) if day_val is not None else self._week_set_for_today()
        except Exception:
            week_set = self._week_set_for_today()

        manual_cfg = self._build_manual_cfg(
            power=power,
            start_time=start_time,
            end_time=end_time,
            week_set=week_set,
            enable=1,
            time_num=6,  # fijo, como tu script
        )

        # --- payload ES.SetMode (usar id=1) ---
        payload = {
            "id": 1,
            "method": "ES.SetMode",
            "params": {
                "id": 1,
                "config": {
                    "mode": "Manual",
                    "manual_cfg": manual_cfg,
                }
            },
        }

        # Log claro del comando que vamos a mandar
        modo_txt = "carga" if power < 0 else "descarga"
        pot_abs = abs(power)
        week_h = self._weekset_human(int(week_set))
        _LOGGER.debug(
            "MANDANDO ORDEN → %s %s, de %s a %s de %s W",
            modo_txt, week_h, start_time, end_time, pot_abs
        )
        _LOGGER.debug("ES.SetMode payload: %s", json.dumps(payload, ensure_ascii=False))

        # Envío real
        fp = json.dumps(payload, sort_keys=True)
        try:
            result = await self._async_send_udp_command(payload, timeout=5.0, retry=3)
            _LOGGER.debug("Respuesta ES.SetMode: %s", result)
            self._last_cmd_fingerprint = fp
        except Exception as e:
            _LOGGER.error("Fallo enviando ES.SetMode a Marstek: %s", e)

    # ---- Ciclo ----
    async def _async_update_data(self) -> dict[str, Any]:
        """
        1) Lee telemetría (EM.GetStatus + Bat.GetStatus + ES.GetMode + ES.GetStatus)
        2) Envía telemetría a Spock
        3) Procesa orden de Spock -> ES.SetMode (Manual / Auto)
        4) Devuelve telemetría + respuesta de Spock
        """
        entry_id = self.config_entry.entry_id
        is_enabled = self.hass.data[DOMAIN].get(entry_id, {}).get("is_enabled", True)
        if not is_enabled:
            _LOGGER.debug("Sondeo API deshabilitado. Omitiendo ciclo.")
            return self.data

        _LOGGER.debug("Iniciando ciclo de actualización unificado de Spock EMS")

        telemetry_data: dict[str, Any] = {}
        em_data: dict[str, Any] | None = None
        bat_data: dict[str, Any] | None = None
        mode_data: dict[str, Any] | None = None
        es_data: dict[str, Any] | None = None  # ES.GetStatus

        # 1) Lecturas (todas con 3 reintentos por defecto)
        try:
            em_payload = {"id": 1, "method": "EM.GetStatus", "params": {"id": 0}}
            em_data = await self._async_send_udp_command(em_payload, timeout=5.0)
        except Exception as e:
            _LOGGER.warning("EM.GetStatus falló: %r", e)

        try:
            bat_payload = {"id": 2, "method": "Bat.GetStatus", "params": {"id": 0}}
            bat_data = await self._async_send_udp_command(bat_payload, timeout=5.0)
            _LOGGER.debug("Bat.GetStatus (raw): %s", bat_data)
        except Exception as e:
            _LOGGER.warning("Bat.GetStatus falló: %r", e)

        try:
            mode_payload = {"id": 3, "method": "ES.GetMode", "params": {"id": 0}}
            mode_data = await self._async_send_udp_command(mode_payload, timeout=5.0)
            _LOGGER.debug("ES.GetMode (raw): %s", mode_data)
        except Exception as e:
            _LOGGER.warning("ES.GetMode falló: %r", e)

        # ES.GetStatus para obtener pv_power y energías
        try:
            es_payload = {"id": 4, "method": "ES.GetStatus", "params": {"id": 0}}
            es_data = await self._async_send_udp_command(es_payload, timeout=5.0)
            _LOGGER.debug("ES.GetStatus (raw): %s", es_data)
        except Exception as e:
            _LOGGER.warning("ES.GetStatus falló: %r", e)

        # 2) Mapeo normalizado
        if em_data is None and bat_data is None and mode_data is None and es_data is None:
            _LOGGER.warning("No se pudo obtener telemetría de Marstek. Enviando nulls.")
            telemetry_data = {
                "plant_id": str(self.plant_id),
                "bat_soc": None,
                "bat_power": None,
                "pv_power": None,
                "ongrid_power": None,
                "bat_charge_allowed": None,
                "bat_discharge_allowed": None,
                "bat_capacity": None,
                "total_grid_output_energy": None,
            }
        else:
            e = em_data or {}
            b = bat_data or {}
            m = mode_data or {}
            es = es_data or {}

            # Batería
            soc = b.get("soc", b.get("bat_soc", m.get("bat_soc")))

            raw_charg_flag = b.get("charg_flag", b.get("charg_ag"))
            raw_dischrg_flag = b.get("dischrg_flag", b.get("dischrg_ag"))

            if raw_charg_flag is None:
                charg_flag: bool | None = None
            else:
                charg_flag = bool(raw_charg_flag)

            if raw_dischrg_flag is None:
                discharg_flag: bool | None = None
            else:
                discharg_flag = bool(raw_dischrg_flag)

            # Potencias
            bat_power = m.get("ongrid_power")       # del equipo (tu FW actual)
            ongrid_power = e.get("total_power")     # EM.GetStatus
            pv_power = es.get("pv_power")           # ES.GetStatus

            # Capacidad (usa rated si existe; normaliza a entero o None)
            raw_rated = b.get("rated_capacity")
            raw_bcap = b.get("bat_capacity", b.get("bat_cap"))

            bat_capacity: int | None
            try:
                cap_num: float | None
                if raw_rated is not None:
                    cap_num = float(raw_rated)
                elif raw_bcap is not None:
                    cap_num = float(raw_bcap)
                else:
                    cap_num = None

                if cap_num is None:
                    bat_capacity = None
                else:
                    if cap_num < 0:
                        cap_num = 0.0
                    bat_capacity = int(round(cap_num))
            except Exception:
                bat_capacity = None

            _LOGGER.debug(
                "Capacidad (rated=%r, bat=%r) => enviada=%s",
                raw_rated,
                raw_bcap,
                bat_capacity,
            )

            telemetry_data = {
                "plant_id": str(self.plant_id),
                "bat_soc": self._str_or_none(soc),
                "bat_power": self._str_or_none(bat_power),
                "pv_power": self._str_or_none(pv_power),
                "ongrid_power": self._str_or_none(ongrid_power),
                "bat_charge_allowed": self._bool_str_or_none(charg_flag),
                "bat_discharge_allowed": self._bool_str_or_none(discharg_flag),
                "bat_capacity": self._str_or_none(bat_capacity),
                "total_grid_output_energy": None,  # aún no lo tenemos → null
            }

            _LOGGER.debug("Telemetría real obtenida (normalizada): %s", telemetry_data)

        # 3) POST a Spock (telemetría → comandos)
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

                # 3.b) Procesar la orden de Spock -> ES.SetMode (Manual / Auto) (envío activo)
                try:
                    await self._apply_spock_command(data)
                except Exception as cmd_err:
                    _LOGGER.error("Error aplicando orden de Spock: %s", cmd_err)

                # 4) Devolvemos telemetría + respuesta Spock (para sensores)
                return {
                    "telemetry": telemetry_data,
                    "spock": data,
                }

        except UpdateFailed:
            raise
        except Exception as err:
            _LOGGER.error("Error en el ciclo de actualización de Spock EMS (API POST): %s", err)
            raise UpdateFailed(f"Error en el ciclo de actualización (API POST): {err}") from err
