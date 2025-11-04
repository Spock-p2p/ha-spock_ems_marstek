"""Switch para habilitar/deshabilitar el sondeo de Spock EMS Marstek."""
from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from . import SpockEnergyCoordinator # Importamos el Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configura el interruptor desde la entrada de configuración."""
    
    coordinator: SpockEnergyCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([SpockEmsSwitch(hass, entry, coordinator)])


class SpockEmsSwitch(CoordinatorEntity[SpockEnergyCoordinator], SwitchEntity):
    """Interruptor para controlar el sondeo de la API."""

    _attr_has_entity_name = True
    _attr_translation_key = "polling_enabled"
    _attr_icon = "mdi:api"

    def __init__(
        self, 
        hass: HomeAssistant, 
        entry: ConfigEntry, 
        coordinator: SpockEnergyCoordinator
    ) -> None:
        """Inicializa el interruptor."""
        super().__init__(coordinator) # Se suscribe al coordinator
        self.hass = hass
        self._entry_id = entry.entry_id
        
        self._attr_unique_id = f"{self._entry_id}_polling_enabled"
        
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._entry_id)},
            name=f"Spock EMS (Planta {coordinator.plant_id})",
            manufacturer="Spock",
            model="Marstek EMS Control",
        )

    @property
    def is_on(self) -> bool:
        """Devuelve true si el sondeo está habilitado."""
        return self.hass.data[DOMAIN].get(self._entry_id, {}).get("is_enabled", True)

    async def async_turn_on(self, **kwargs) -> None:
        """Habilita el sondeo."""
        _LOGGER.debug("Habilitando sondeo API")
        self.hass.data[DOMAIN][self._entry_id]["is_enabled"] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Deshabilita el sondeo."""
        _LOGGER.debug("Deshabilitando sondeo API")
        self.hass.data[DOMAIN][self._entry_id]["is_enabled"] = False
        self.async_write_ha_state()
        
    @callback
    def _handle_coordinator_update(self) -> None:
        """
        Este switch es un "listener" pero no necesita actualizar su estado
        cuando el coordinator termina, ya que su estado (on/off) es
        controlado por el usuario, no por los datos de la API.
        
        Aun así, mantenemos la herencia de CoordinatorEntity para
        asegurar que el coordinador sepa que tiene un listener.
        """
        # Opcional: si quisiéramos que el switch se ponga "no disponible"
        # si la API falla, podríamos añadir:
        # self.async_write_ha_state()
        # Pero por ahora lo dejamos independiente.
        pass
