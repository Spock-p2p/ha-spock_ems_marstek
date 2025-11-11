from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, add_entities: AddEntitiesCallback):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    add_entities([SpockPollingSwitch(coordinator, entry)])


class SpockPollingSwitch(CoordinatorEntity, SwitchEntity):
    _attr_icon = "mdi:update"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Spock EMS Marstek: Polling habilitado"
        self._attr_unique_id = f"{entry.entry_id}_polling_enabled"

    @property
    def is_on(self) -> bool:
        store = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        return bool(store.get("is_enabled", True))

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._set_enabled(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._set_enabled(False)

    def _set_enabled(self, value: bool) -> None:
        # Guarda flag y fuerza refresh para que los sensores se actualicen (o no)
        self.hass.data[DOMAIN][self._entry.entry_id]["is_enabled"] = value
        # Dispara un refresh inmediato del coordinator (respetando la lógica de skip si está apagado)
        self.coordinator.request_refresh()
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Spock EMS Marstek",
            manufacturer="Spock",
            model="Venus 3.x (Local API)",
        )
