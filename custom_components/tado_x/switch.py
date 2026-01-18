"""Switch platform for Tado X."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TadoXDataUpdateCoordinator, TadoXDevice, TadoXRoom

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tado X switch entities."""
    coordinator: TadoXDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SwitchEntity] = []

    # Add boost mode switches for each room
    for room_id in coordinator.data.rooms:
        entities.append(TadoXBoostModeSwitch(coordinator, room_id))

    # Add child lock switches for devices that support it
    for device in coordinator.data.devices.values():
        if device.device_type in ("VA04", "TR04"):  # Valves and Thermostats
            entities.append(TadoXChildLockSwitch(coordinator, device.serial_number))

    async_add_entities(entities)


class TadoXBoostModeSwitch(CoordinatorEntity[TadoXDataUpdateCoordinator], SwitchEntity):
    """Tado X boost mode switch for a room."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:rocket-launch"

    def __init__(
        self,
        coordinator: TadoXDataUpdateCoordinator,
        room_id: int,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self._room_id = room_id
        self._attr_unique_id = f"{coordinator.home_id}_{room_id}_boost_mode"
        self._attr_name = "Boost mode"

    @property
    def _room(self) -> TadoXRoom | None:
        """Get the room data."""
        return self.coordinator.data.rooms.get(self._room_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        room = self._room
        room_name = room.name if room else f"Room {self._room_id}"

        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.home_id}_{self._room_id}")},
            name=room_name,
            manufacturer="Tado",
            model="Tado X Room",
            via_device=(DOMAIN, str(self.coordinator.home_id)),
        )

    @property
    def is_on(self) -> bool:
        """Return true if boost mode is active."""
        room = self._room
        return room.boost_mode if room else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on boost mode."""
        await self.coordinator.api.set_room_boost(self._room_id, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off boost mode."""
        await self.coordinator.api.set_room_boost(self._room_id, False)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()


class TadoXChildLockSwitch(CoordinatorEntity[TadoXDataUpdateCoordinator], SwitchEntity):
    """Tado X child lock switch for a device."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:lock"
    _attr_entity_registry_enabled_default = False  # Disabled by default

    def __init__(
        self,
        coordinator: TadoXDataUpdateCoordinator,
        serial_number: str,
    ) -> None:
        """Initialize the switch entity."""
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._attr_unique_id = f"{serial_number}_child_lock"
        self._attr_name = "Child lock"

    @property
    def _device(self) -> TadoXDevice | None:
        """Get the device data."""
        return self.coordinator.data.devices.get(self._serial_number)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        device = self._device
        if not device:
            return DeviceInfo(
                identifiers={(DOMAIN, self._serial_number)},
            )

        device_type_names_fr = {
            "VA04": "Vanne",
            "SU04": "Capteur Temp",
            "TR04": "Thermostat",
            "IB02": "Bridge X",
        }

        device_type_models = {
            "VA04": "Radiator Valve X",
            "SU04": "Temperature Sensor X",
            "TR04": "Thermostat X",
            "IB02": "Bridge X",
        }

        via_device_id = (
            (DOMAIN, f"{self.coordinator.home_id}_{device.room_id}")
            if device.room_id
            else (DOMAIN, str(self.coordinator.home_id))
        )

        device_name_parts = [device_type_names_fr.get(device.device_type, device.device_type)]
        if device.room_name:
            device_name_parts.append(device.room_name)

        return DeviceInfo(
            identifiers={(DOMAIN, self._serial_number)},
            name=" ".join(device_name_parts),
            manufacturer="Tado",
            model=device_type_models.get(device.device_type, device.device_type),
            sw_version=device.firmware_version,
            via_device=via_device_id,
        )

    @property
    def is_on(self) -> bool:
        """Return true if child lock is enabled."""
        device = self._device
        return device.child_lock_enabled if device else False

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        device = self._device
        return device is not None and device.connection_state == "CONNECTED"

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable child lock."""
        await self.coordinator.api.set_device_child_lock(self._serial_number, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable child lock."""
        await self.coordinator.api.set_device_child_lock(self._serial_number, False)
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
