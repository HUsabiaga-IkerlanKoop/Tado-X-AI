"""DataUpdateCoordinator for Tado X."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Callable

from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import TadoXApi, TadoXApiError, TadoXAuthError
from .const import (
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_OFFSET_HYSTERESIS,
    DOMAIN,
    GEOFENCING_SOURCE_HA,
    GEOFENCING_SOURCE_OFF,
    GEOFENCING_SOURCE_TADO,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class TadoXDevice:
    """Representation of a Tado X device."""

    serial_number: str
    device_type: str
    firmware_version: str
    connection_state: str
    battery_state: str | None = None
    temperature_measured: float | None = None
    temperature_offset: float = 0.0
    mounting_state: str | None = None
    child_lock_enabled: bool = False
    room_id: int | None = None
    room_name: str | None = None


@dataclass
class TadoXRoom:
    """Representation of a Tado X room."""

    room_id: int
    name: str
    current_temperature: float | None = None
    target_temperature: float | None = None
    humidity: float | None = None
    heating_power: int = 0
    power: str = "OFF"
    connection_state: str = "DISCONNECTED"
    manual_control_active: bool = False
    manual_control_remaining_seconds: int | None = None
    manual_control_type: str | None = None
    boost_mode: bool = False
    open_window_detected: bool = False
    next_schedule_change: str | None = None
    next_schedule_temperature: float | None = None
    devices: list[TadoXDevice] = field(default_factory=list)


@dataclass
class TadoXData:
    """Data from Tado X API."""

    home_id: int
    home_name: str
    presence: str | None = None
    rooms: dict[int, TadoXRoom] = field(default_factory=dict)
    devices: dict[str, TadoXDevice] = field(default_factory=dict)
    other_devices: list[TadoXDevice] = field(default_factory=list)


class TadoXDataUpdateCoordinator(DataUpdateCoordinator[TadoXData]):
    """Class to manage fetching Tado X data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: TadoXApi,
        home_id: int,
        home_name: str,
        scan_interval: int = DEFAULT_SCAN_INTERVAL,
        geofencing_enabled: bool = False,
        min_temp: float | None = None,
        max_temp: float | None = None,
        auto_offset_sync: bool = False,
        room_configs: list[dict[str, str]] | None = None,
        offset_hysteresis: float = DEFAULT_OFFSET_HYSTERESIS,
        presence_entities: list[str] | None = None,
        geofencing_source: str = GEOFENCING_SOURCE_OFF,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.home_id = home_id
        self.home_name = home_name
        self.api.home_id = home_id
        self.geofencing_source = geofencing_source
        # Backwards-compat flag: True whenever any source is active
        self.geofencing_enabled = geofencing_enabled and geofencing_source != GEOFENCING_SOURCE_OFF
        self.min_temp = min_temp
        self.max_temp = max_temp
        self.auto_offset_sync = auto_offset_sync
        self.room_configs = room_configs or []
        self.offset_hysteresis = offset_hysteresis
        self.presence_entities: list[str] = presence_entities or []
        self._pending_offset_updates: dict[str, float] = {}
        self._presence_unsub: Callable[[], None] | None = None

        _LOGGER.info(
            "TadoXDataUpdateCoordinator initialized - Home: %s (ID: %s), Geofencing source: %s, HA Presence Entities: %s, Auto Offset Sync: %s",
            home_name,
            home_id,
            self.geofencing_source,
            self.presence_entities or "<none>",
            auto_offset_sync,
        )

    async def async_batch_update_temperature_offsets(
        self, offsets: dict[str, float]
    ) -> dict[str, str]:
        """Update multiple device temperature offsets in a single operation.
        
        This method batches multiple offset updates and executes them in parallel,
        minimizing the time window and ensuring all updates happen during the same
        refresh cycle.
        
        Args:
            offsets: Dictionary mapping device serial numbers to offset values
        
        Returns:
            Dictionary with results for each device
        """
        _LOGGER.info("Batch updating %d device temperature offsets", len(offsets))
        results = await self.api.set_multiple_device_temperature_offsets(offsets)
        
        # Request a coordinator refresh to update entities with new values
        await self.async_request_refresh()
        
        return results

    def _evaluate_ha_presence(self) -> tuple[bool, int, list[str]]:
        """Evaluate presence from configured HA entities.

        Returns (any_home, known_count, devices_home_names). Unknown/unavailable
        states are ignored so a temporarily missing tracker does not force AWAY.
        """
        any_home = False
        known = 0
        names: list[str] = []
        for entity_id in self.presence_entities:
            state = self.hass.states.get(entity_id)
            if state is None or state.state in ("unknown", "unavailable", None):
                continue
            known += 1
            value = state.state
            at_home = False
            if entity_id.startswith("zone."):
                # zone state is the count of trackers in the zone
                try:
                    at_home = int(value) > 0
                except (TypeError, ValueError):
                    at_home = False
            else:
                at_home = value in ("home", "on")
            if at_home:
                any_home = True
                names.append(state.attributes.get("friendly_name") or entity_id)
        return any_home, known, names

    async def _apply_presence_decision(
        self, any_home: bool, known: int, devices_home: list[str], current_presence: str | None
    ) -> str | None:
        """Apply HOME/AWAY decision against current Tado presence.

        Always re-asserts the presenceLock (even when Tado already reports the
        target state) so the Tado mobile app never falls back to its native
        "confirm switch" prompt — the lock is an unconditional server-side
        override.
        """
        if known == 0:
            _LOGGER.debug("HA presence: no known trackers, leaving presence unchanged")
            return current_presence
        target = "HOME" if any_home else "AWAY"
        if target != current_presence:
            _LOGGER.info(
                "HA presence: switching Tado %s -> %s (devices home: %s)",
                current_presence,
                target,
                devices_home,
            )
        else:
            _LOGGER.debug(
                "HA presence: re-asserting lock=%s (devices home: %s)",
                target,
                devices_home,
            )
        await self.api.set_presence(target)
        return target

    async def async_ha_presence_check(self, home_state: dict[str, Any] | None = None) -> str | None:
        """Evaluate HA presence entities and sync Tado presence accordingly."""
        try:
            if home_state is None:
                home_state = await self.api.get_home_state()
            current = home_state.get("presence")
            any_home, known, names = self._evaluate_ha_presence()
            return await self._apply_presence_decision(any_home, known, names, current)
        except Exception as err:  # noqa: BLE001 - log + degrade gracefully
            _LOGGER.error("HA presence check failed: %s", err, exc_info=True)
            return home_state.get("presence") if home_state else None

    @callback
    def async_setup_presence_listener(self) -> Callable[[], None] | None:
        """Subscribe to state changes of configured HA presence entities.

        Returns an unsubscribe callable, or None if there is nothing to listen to.
        """
        # Tear down any previous listener (e.g. after options reload)
        if self._presence_unsub is not None:
            self._presence_unsub()
            self._presence_unsub = None

        if not (self.geofencing_enabled and self.presence_entities):
            return None

        if self.geofencing_source != GEOFENCING_SOURCE_HA:
            return None

        @callback
        def _handle_state_change(event: Event) -> None:
            new_state = event.data.get("new_state")
            old_state = event.data.get("old_state")
            new_val = new_state.state if new_state else None
            old_val = old_state.state if old_state else None
            if new_val == old_val:
                return
            _LOGGER.debug(
                "Presence entity %s changed %s -> %s; re-evaluating",
                event.data.get("entity_id"),
                old_val,
                new_val,
            )
            self.hass.async_create_task(self._async_presence_event_handler())

        self._presence_unsub = async_track_state_change_event(
            self.hass, self.presence_entities, _handle_state_change
        )
        _LOGGER.info(
            "Subscribed to %d HA presence entity state changes",
            len(self.presence_entities),
        )
        return self._presence_unsub

    async def _async_presence_event_handler(self) -> None:
        """Apply presence decision and refresh coordinator on tracker changes."""
        new_presence = await self.async_ha_presence_check()
        # Reflect the change in coordinator data without waiting for next poll
        if self.data is not None and new_presence is not None and new_presence != self.data.presence:
            self.data.presence = new_presence
            self.async_update_listeners()

    async def async_geofencing_check(self, home_state: dict[str, Any] | None = None) -> str | None:
        """Check geofencing status and set home/away mode.

        Branches on ``geofencing_source``:
        - ``ha``  : use configured HA presence entities as source of truth.
        - ``tado``: poll Tado mobile devices (legacy behavior).
        - ``off`` : do nothing.
        """
        if self.geofencing_source == GEOFENCING_SOURCE_OFF:
            return home_state.get("presence") if home_state else None
        if self.geofencing_source == GEOFENCING_SOURCE_HA:
            return await self.async_ha_presence_check(home_state)
        # Default: GEOFENCING_SOURCE_TADO
        try:
            # Get home presence state (re-use provided state to avoid extra call)
            if home_state is None:
                home_state = await self.api.get_home_state()
            presence = home_state.get("presence")
            _LOGGER.info("Geofencing check - Current presence: %s", presence)

            # Get mobile devices
            mobile_devices = await self.api.get_mobile_devices()
            _LOGGER.info("Geofencing check - Retrieved %d mobile devices", len(mobile_devices))
            
            devices_home = []
            for device in mobile_devices:
                device_name = device.get("name", "Unknown")
                geo_enabled = device.get("settings", {}).get("geoTrackingEnabled", False)
                location = device.get("location")
                at_home = location.get("atHome") if location else None
                
                _LOGGER.debug(
                    "Geofencing check - Device: %s, GeoTracking: %s, AtHome: %s",
                    device_name,
                    geo_enabled,
                    at_home,
                )
                
                if geo_enabled and location and location.get("atHome"):
                    devices_home.append(device_name)

            _LOGGER.info("Geofencing check - Devices at home: %s", devices_home)

            # Always re-assert the lock so Tado's app never prompts the user to
            # confirm a HOME/AWAY switch — the presenceLock is an unconditional
            # server-side override and idempotent if already in that state.
            target = "HOME" if devices_home else "AWAY"
            if target != presence:
                _LOGGER.info("Geofencing: switching Tado %s -> %s", presence, target)
            else:
                _LOGGER.debug("Geofencing: re-asserting lock=%s", target)
            await self.api.set_presence(target)
            presence = target

            return presence
        except Exception as e:
            _LOGGER.error("Geofencing check failed: %s", e, exc_info=True)
            return home_state.get("presence") if home_state else None

    async def _async_update_data(self) -> TadoXData:
        """Fetch data from Tado X API."""
        try:
            # Always fetch home state to expose geofencing presence
            home_state = await self.api.get_home_state()
            presence = home_state.get("presence")

            # Run geofencing check if enabled and update presence with result
            _LOGGER.debug("Geofencing enabled: %s", self.geofencing_enabled)
            if self.geofencing_enabled:
                _LOGGER.info("Running geofencing check...")
                updated_presence = await self.async_geofencing_check(home_state)
                if updated_presence is not None:
                    presence = updated_presence
            else:
                _LOGGER.debug("Geofencing is disabled, skipping check")
            # Get rooms with current state
            rooms_data = await self.api.get_rooms()

            # Get rooms with devices
            rooms_devices_data = await self.api.get_rooms_and_devices()

            # Process the data
            data = TadoXData(
                home_id=self.home_id,
                home_name=self.home_name,
                presence=presence,
            )

            # Process rooms and devices
            rooms_info = rooms_devices_data.get("rooms", [])
            room_devices_map: dict[int, list[dict]] = {}

            for room_info in rooms_info:
                room_id = room_info.get("roomId")
                if room_id:
                    room_devices_map[room_id] = room_info.get("devices", [])

            # Process room states
            for room_data in rooms_data:
                room_id = room_data.get("id")
                if not room_id:
                    continue

                # Debug: log raw room data for power/setting analysis
                setting = room_data.get("setting") or {}
                _LOGGER.debug(
                    "Room %s (%s) - setting: %s, manualControl: %s",
                    room_id,
                    room_data.get("name"),
                    setting,
                    room_data.get("manualControlTermination"),
                )

                # Get sensor data (use 'or {}' to handle None values)
                sensor_data = room_data.get("sensorDataPoints") or {}
                inside_temp = sensor_data.get("insideTemperature") or {}
                humidity_data = sensor_data.get("humidity") or {}

                # Get setting (use 'or {}' to handle None values)
                setting = room_data.get("setting") or {}
                target_temp = setting.get("temperature") or {}

                # Get manual control info
                manual_control = room_data.get("manualControlTermination")
                manual_active = manual_control is not None
                manual_remaining = None
                manual_type = None
                if manual_control:
                    manual_remaining = manual_control.get("remainingTimeInSeconds")
                    manual_type = manual_control.get("type")

                # Get next schedule change (use 'or {}' to handle None values)
                next_change = room_data.get("nextScheduleChange") or {}
                next_change_time = next_change.get("start")
                next_change_setting = next_change.get("setting") or {}
                next_change_temp_obj = next_change_setting.get("temperature") or {}
                next_change_temp = next_change_temp_obj.get("value")

                # Get heating power and connection (use 'or {}' to handle None values)
                heating_power_data = room_data.get("heatingPower") or {}
                connection_data = room_data.get("connection") or {}

                room = TadoXRoom(
                    room_id=room_id,
                    name=room_data.get("name", f"Room {room_id}"),
                    current_temperature=inside_temp.get("value"),
                    target_temperature=target_temp.get("value"),
                    humidity=humidity_data.get("percentage"),
                    heating_power=heating_power_data.get("percentage", 0),
                    power=setting.get("power", "OFF"),
                    connection_state=connection_data.get("state", "DISCONNECTED"),
                    manual_control_active=manual_active,
                    manual_control_remaining_seconds=manual_remaining,
                    manual_control_type=manual_type,
                    boost_mode=room_data.get("boostMode") is not None,
                    open_window_detected=room_data.get("openWindow") is not None,
                    next_schedule_change=next_change_time,
                    next_schedule_temperature=next_change_temp,
                )

                # Add devices for this room
                for device_data in room_devices_map.get(room_id, []):
                    device_connection = device_data.get("connection") or {}
                    device = TadoXDevice(
                        serial_number=device_data.get("serialNumber", ""),
                        device_type=device_data.get("type", ""),
                        firmware_version=device_data.get("firmwareVersion", ""),
                        connection_state=device_connection.get("state", "DISCONNECTED"),
                        battery_state=device_data.get("batteryState"),
                        temperature_measured=device_data.get("temperatureAsMeasured"),
                        temperature_offset=device_data.get("temperatureOffset", 0.0),
                        mounting_state=device_data.get("mountingState"),
                        child_lock_enabled=device_data.get("childLockEnabled", False),
                        room_id=room_id,
                        room_name=room.name,
                    )
                    room.devices.append(device)
                    data.devices[device.serial_number] = device

                data.rooms[room_id] = room

            # Process other devices (bridge, thermostat controller)
            # First, find the room with the most devices (for thermostat association)
            room_with_most_devices: int | None = None
            max_device_count = 0
            for room_id, room in data.rooms.items():
                device_count = len(room.devices)
                if device_count > max_device_count:
                    max_device_count = device_count
                    room_with_most_devices = room_id

            for device_data in rooms_devices_data.get("otherDevices") or []:
                other_device_connection = device_data.get("connection") or {}
                other_room_id = device_data.get("roomId")
                other_room_name = None
                device_type = device_data.get("type", "")

                # If device has a room association from API, use it
                if other_room_id and other_room_id in data.rooms:
                    other_room_name = data.rooms[other_room_id].name
                # For Thermostat X (TR04) without room, associate with the room
                # that has the most devices (typically the main room it controls)
                elif device_type == "TR04" and room_with_most_devices:
                    other_room_id = room_with_most_devices
                    other_room_name = data.rooms[room_with_most_devices].name
                    _LOGGER.debug(
                        "Associating Thermostat X %s with room %s (%s) - room has %d devices",
                        device_data.get("serialNumber"),
                        other_room_id,
                        other_room_name,
                        max_device_count,
                    )

                device = TadoXDevice(
                    serial_number=device_data.get("serialNumber", ""),
                    device_type=device_type,
                    firmware_version=device_data.get("firmwareVersion", ""),
                    connection_state=other_device_connection.get("state", "DISCONNECTED"),
                    battery_state=device_data.get("batteryState"),
                    temperature_measured=device_data.get("temperatureAsMeasured"),
                    temperature_offset=device_data.get("temperatureOffset", 0.0),
                    room_id=other_room_id,
                    room_name=other_room_name,
                )

                # If device has a room, add it to the room's device list
                if other_room_id and other_room_id in data.rooms:
                    data.rooms[other_room_id].devices.append(device)

                data.other_devices.append(device)
                data.devices[device.serial_number] = device

            # Auto-sync temperature offsets if enabled
            if self.auto_offset_sync and self.room_configs:
                await self._auto_sync_temperature_offsets(data)

            return data

        except TadoXAuthError as err:
            raise UpdateFailed(f"Authentication error: {err}") from err
        except TadoXApiError as err:
            raise UpdateFailed(f"API error: {err}") from err
        except Exception as err:
            _LOGGER.exception("Unexpected error fetching Tado X data")
            raise UpdateFailed(f"Unexpected error: {err}") from err

    async def _auto_sync_temperature_offsets(self, data: TadoXData) -> None:
        """Automatically sync temperature offsets based on configured room mappings.
        
        This runs during the coordinator update cycle, using entity IDs instead of
        device serials for easier configuration.
        
        Room config format: [{"offset_entity": "number.room_offset", "temperature_sensor": "sensor.room_temp"}]
        """
        offsets_to_update: dict[str, float] = {}
        
        from homeassistant.helpers import entity_registry as er
        entity_registry = er.async_get(self.hass)
        
        for room_config in self.room_configs:
            offset_entity_id = room_config.get("offset_entity")
            temp_sensor_entity_id = room_config.get("temperature_sensor")
            
            if not offset_entity_id or not temp_sensor_entity_id:
                _LOGGER.warning("Invalid room config: %s", room_config)
                continue
            
            # Get the offset entity to find its device
            offset_entity = entity_registry.async_get(offset_entity_id)
            if not offset_entity or not offset_entity.device_id:
                _LOGGER.debug("Offset entity %s not found or has no device", offset_entity_id)
                continue
            
            # Get device serial from the device registry
            from homeassistant.helpers import device_registry as dr
            device_registry = dr.async_get(self.hass)
            device = device_registry.async_get(offset_entity.device_id)
            if not device:
                _LOGGER.debug("Device not found for entity %s", offset_entity_id)
                continue
            
            # Extract serial number from device identifiers
            device_serial = None
            for identifier in device.identifiers:
                if identifier[0] == DOMAIN and len(identifier) > 1:
                    # Serial is usually part of the identifier
                    device_serial = str(identifier[1])
                    break
            
            if not device_serial:
                _LOGGER.debug("Could not find serial for device %s", device.id)
                continue
            
            # Get device data from coordinator
            device_data = data.devices.get(device_serial)
            if not device_data:
                _LOGGER.debug("Device %s not found in coordinator data", device_serial)
                continue
            
            # Get valve temperature (raw measurement)
            valve_temp = device_data.temperature_measured
            if valve_temp is None:
                _LOGGER.debug("Device %s has no temperature measurement", device_serial)
                continue
            
            # Get current offset
            current_offset = device_data.temperature_offset
            
            # Get room sensor temperature from Home Assistant state
            room_sensor_state = self.hass.states.get(temp_sensor_entity_id)
            if not room_sensor_state or room_sensor_state.state in ("unknown", "unavailable"):
                _LOGGER.debug("Room sensor %s unavailable", temp_sensor_entity_id)
                continue
            
            try:
                room_temp = float(room_sensor_state.state)
            except (ValueError, TypeError):
                _LOGGER.warning("Invalid temperature from %s: %s", 
                               temp_sensor_entity_id, room_sensor_state.state)
                continue
            
            # Calculate required offset: room_temp - valve_temp
            calculated_offset = round(room_temp - valve_temp, 1)
            
            # Clamp to valid range (-3 to +3 for safety)
            new_offset = max(-3.0, min(3.0, calculated_offset))
            
            # Check if update needed (hysteresis)
            offset_delta = abs(new_offset - current_offset)
            if offset_delta > self.offset_hysteresis:
                offsets_to_update[device_serial] = new_offset
                _LOGGER.info(
                    "Offset sync for %s (%s): room=%.1f°C, valve=%.1f°C, "
                    "current_offset=%.1f°C, new_offset=%.1f°C (delta=%.1f°C)",
                    offset_entity_id, device_serial, room_temp, valve_temp, 
                    current_offset, new_offset, offset_delta
                )
            else:
                _LOGGER.debug(
                    "Offset for %s within hysteresis (delta=%.1f°C < %.1f°C)",
                    offset_entity_id, offset_delta, self.offset_hysteresis
                )
        
        # Apply all offset updates in parallel if any are needed
        if offsets_to_update:
            _LOGGER.info("Auto-syncing %d device offsets", len(offsets_to_update))
            try:
                results = await self.api.set_multiple_device_temperature_offsets(offsets_to_update)
                
                # Log results
                success_count = sum(1 for status in results.values() if status == "success")
                _LOGGER.info(
                    "Auto offset sync completed: %d successful, %d failed",
                    success_count, len(results) - success_count
                )
                
                for device_serial, status in results.items():
                    if status != "success":
                        _LOGGER.error("Failed to auto-sync offset for %s: %s", 
                                     device_serial, status)
            except Exception as err:
                _LOGGER.error("Failed to auto-sync offsets: %s", err)
        else:
            _LOGGER.debug("No offset updates needed (all within hysteresis)")

