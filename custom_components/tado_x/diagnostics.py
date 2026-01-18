"""Diagnostics support for Tado X."""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import TadoXDataUpdateCoordinator

TO_REDACT = {
    "access_token",
    "refresh_token",
    "serialNumber",
    "serial_number",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: TadoXDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    diagnostics_data = {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "domain": entry.domain,
            "title": entry.title,
            "data": dict(entry.data),
            "options": dict(entry.options),
        },
        "coordinator": {
            "home_id": coordinator.home_id,
            "home_name": coordinator.home_name,
            "scan_interval": coordinator.update_interval.total_seconds(),
            "geofencing_enabled": coordinator.geofencing_enabled,
            "auto_offset_sync": coordinator.auto_offset_sync,
            "offset_hysteresis": coordinator.offset_hysteresis,
            "last_update_success": coordinator.last_update_success,
        },
        "data": {
            "rooms": [
                {
                    "room_id": room.room_id,
                    "name": room.name,
                    "current_temperature": room.current_temperature,
                    "target_temperature": room.target_temperature,
                    "humidity": room.humidity,
                    "heating_power": room.heating_power,
                    "power": room.power,
                    "connection_state": room.connection_state,
                    "manual_control_active": room.manual_control_active,
                    "boost_mode": room.boost_mode,
                    "open_window_detected": room.open_window_detected,
                    "device_count": len(room.devices),
                }
                for room in coordinator.data.rooms.values()
            ],
            "devices": [
                {
                    "device_type": device.device_type,
                    "firmware_version": device.firmware_version,
                    "connection_state": device.connection_state,
                    "battery_state": device.battery_state,
                    "temperature_measured": device.temperature_measured,
                    "temperature_offset": device.temperature_offset,
                    "mounting_state": device.mounting_state,
                    "child_lock_enabled": device.child_lock_enabled,
                    "room_name": device.room_name,
                }
                for device in coordinator.data.devices.values()
            ],
            "presence": coordinator.data.presence,
        },
    }

    return async_redact_data(diagnostics_data, TO_REDACT)
