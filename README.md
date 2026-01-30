# Tado X Integration for Home Assistant (Enhanced)

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

A comprehensive Home Assistant custom integration for **Tado X** devices (the new generation of Tado smart thermostats and radiator valves).

> **Note:** This integration is specifically designed for Tado X devices. For older Tado devices (V3+ and earlier), use the [official Tado integration](https://www.home-assistant.io/integrations/tado/).

## Credits and Origins

This integration is based on the excellent work by **@exabird** in the original [ha-tado-x](https://github.com/exabird/ha-tado-x) repository. The original implementation provided the foundation for Tado X API authentication, device discovery, and basic climate control.

**Enhancements and additional features** in this fork include:
- Geofencing support with automatic HOME/AWAY switching
- Automatic temperature offset synchronization with external sensors
- Binary sensors for window detection, heating state, and connectivity
- Switches for boost mode and child lock control
- Enhanced device temperature sensors (raw and offset-corrected values)
- Additional services for presence control
- Extended attributes on all entities
- Full diagnostics support for troubleshooting

---

## Features Overview

### Core Entities

| Entity Type | Description |
|-------------|-------------|
| **Climate** | Full temperature control with HVAC modes (Heat/Off/Auto) and preset modes (Schedule/Boost). Includes heating power, manual control status, and next schedule information as attributes. |
| **Sensors** | Room temperature, humidity, heating power percentage, device temperatures (raw and corrected), battery status, and geofencing presence. |
| **Binary Sensors** | Open window detection, heating active status, manual control indicator, device connectivity, and low battery warnings. |
| **Switches** | Per-room boost mode control and per-device child lock toggle. |
| **Numbers** | Temperature offset adjustment for fine-tuning device readings. |

### Advanced Features

#### 1. **Geofencing Support**
Automatically switches your home between HOME and AWAY modes based on mobile device location tracking:
- Monitors all geotracking-enabled mobile devices
- Switches to HOME when at least one device is present
- Switches to AWAY when no devices are home
- Exposes home presence as a sensor entity

**Configuration (YAML):**
```yaml
tado_x:
  geofencing_enabled: true
```

**Or via UI:** Settings → Devices & Services → Tado X → Configure → Enable geofencing

#### 2. **Automatic Temperature Offset Synchronization**
Automatically adjusts device temperature offsets based on external room sensors to improve heating accuracy:
- Uses more accurate external temperature sensors as reference
- Applies hysteresis to prevent oscillation
- Updates offsets in parallel for minimal API impact
- Configurable per-room mapping

**Configuration (YAML):**
```yaml
tado_x:
  auto_offset_sync: true
  offset_hysteresis: 0.5  # Minimum change to trigger update (°C)
  rooms:
    - offset_entity: number.valve_egongela_temperature_offset
      temperature_sensor: sensor.air_quality_egongela_temperature
    - offset_entity: number.valve_logela_temperature_offset
      temperature_sensor: sensor.aqara_logela_temperature
```

**How it works:**
- Reads the valve's raw temperature measurement
- Compares with the external room sensor
- Calculates required offset: `offset = room_temp - valve_temp`
- Applies offset only if change exceeds `offset_hysteresis`
- Clamps offset to ±3.0°C for safety

#### 3. **Enhanced Temperature Sensors**
Each device now exposes two temperature sensors:
- **Device Temperature**: Raw measurement from the device sensor (no offset applied)
- **Device Temperature (Corrected)**: Measurement with current offset applied

This allows you to:
- Monitor actual device sensor readings
- Compare raw vs. corrected temperatures
- Validate offset adjustments
- Use raw measurements for offset sync calculations

#### 4. **Control Switches**
- **Boost Mode** (per room): Quick temperature boost without changing schedules
- **Child Lock** (per device): Prevent physical button control on valves and thermostats (disabled by default in UI)

#### 5. **Services**

##### `tado_x.batch_update_temperature_offsets`
Update multiple device temperature offsets simultaneously:
```yaml
service: tado_x.batch_update_temperature_offsets
data:
  offsets:
    "RU01234567890": 2.5
    "RU09876543210": -1.0
```

##### `tado_x.set_presence`
Manually set home presence state:
```yaml
service: tado_x.set_presence
data:
  presence: "HOME"  # or "AWAY"
```

#### 6. **Diagnostics Support**
Full diagnostic data export available via Settings → Devices & Services → Tado X → Device → Download Diagnostics. Includes:
- Coordinator configuration and status
- All room and device states
- Connection states and firmware versions
- Temperature measurements and offsets
- Automatically redacts sensitive data (tokens, serial numbers)

---

## Supported Devices

| Model Code | Device Name | Features |
|------------|-------------|----------|
| VA04 | Radiator Valve X | Temperature control, battery, connectivity, child lock, raw temperature sensor |
| SU04 | Temperature Sensor X | Temperature measurement, battery, connectivity, raw temperature sensor |
| TR04 | Thermostat X | Wall-mounted control, temperature measurement, child lock, raw temperature sensor |
| IB02 | Bridge X | Communication hub, connectivity status |

All supported devices expose:
- Firmware version (as attribute)
- Connection state (binary sensor)
- Device-specific features (battery, temperature, etc.)

---

## Installation

### HACS Installation (Recommended)

1. **Add Custom Repository:**
   - Open HACS → ⋮ (top right) → Custom repositories
   - Add this repository URL as **Integration**
   - Or use: [![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HUsabiaga-IkerlanKoop&repository=Tado-X-AI&category=integration)

2. **Install:**
   - Search "Tado X" in HACS
   - Click **Download**

3. **Restart Home Assistant**

4. **Configure:**
   - Settings → Devices & Services → Add Integration
   - Search "Tado X"
   - Follow the OAuth device authentication flow

### Manual Installation

1. Download the `custom_components/tado_x` folder from this repository
2. Copy it to your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant
4. Add integration via UI

---

## Configuration

### Basic Setup (UI Only)
The integration can be fully configured through the Home Assistant UI:
1. Settings → Devices & Services → Tado X → Configure
2. Set scan interval (default: 860 seconds)
3. Enable geofencing (optional)
4. Set temperature limits (optional)

### Advanced Setup (YAML + UI)

For advanced features, add to your `configuration.yaml`:

```yaml
tado_x:
  scan_interval: 860  # Polling interval in seconds (default: 14.3 minutes)
  geofencing_enabled: true  # Enable automatic HOME/AWAY switching
  auto_offset_sync: true  # Enable automatic temperature offset adjustment
  offset_hysteresis: 0.5  # Minimum offset change to trigger update (°C)
  rooms:
    - offset_entity: number.valve_room1_temperature_offset
      temperature_sensor: sensor.external_room1_temperature
    - offset_entity: number.valve_room2_temperature_offset
      temperature_sensor: sensor.external_room2_temperature
```

**Configuration Priority:** YAML settings override UI settings, allowing you to enforce specific values.

---

## API Rate Limits & Polling Strategy

| Tado Subscription | Daily API Limit |
|-------------------|-----------------|
| Without Auto-Assist | 100 requests/day |
| With Auto-Assist | 20,000 requests/day |

**Default polling:** Every 860 seconds (~14.3 minutes) = ~100 requests/day

**Recommendations:**
- **Without Auto-Assist:** Use default (860s) or higher to stay under 100 requests/day
- **With Auto-Assist:** Can reduce to 60-300 seconds for more responsive control
- Monitor your usage in Home Assistant logs if entities become unavailable

**Rate Limit Behavior:**
- If limit exceeded, API returns errors and entities become unavailable
- Resets daily at midnight UTC
- Consider Auto-Assist subscription for frequent updates or large homes

---

## Troubleshooting

### Authentication Issues
- Go to Settings → Devices & Services → Tado X → ⋮ → Reconfigure
- Follow the OAuth flow again with your Tado account

### Entities Unavailable / Rate Limiting
1. Check Home Assistant logs for API errors
2. Verify your daily API usage
3. Increase `scan_interval` or wait until daily reset
4. Consider Tado Auto-Assist subscription

### Geofencing Not Working
1. **Enable geofencing:**
   - Verify `geofencing_enabled: true` in YAML configuration, or
   - Enable via Settings → Devices & Services → Tado X → Configure
2. **Check mobile device settings:**
   - Ensure mobile devices have geotracking enabled in the Tado app
   - Open Tado mobile app → Settings → Geofencing → Enable for each device
3. **Monitor the presence sensor:**
   - Check `sensor.tado_x_home_geofencing_presence` entity state
   - Should show "HOME", "AWAY", or "UNKNOWN"
   - State updates every scan interval (default: 14.3 minutes)
4. **Check logs for errors:**
   - Search for "Geofencing" in Home Assistant logs
   - Look for messages like "Devices at home, switching to HOME mode"
   - If you see "Geofencing check failed", there may be an API issue
5. **Common issues:**
   - **Sensor shows old state:** Fixed in latest version - update the integration
   - **No automatic switching:** Verify at least one mobile device has `geoTrackingEnabled: true` in Tado app
   - **Delayed response:** Normal - geofencing checks every scan_interval seconds

### Offset Sync Not Working
- Verify `auto_offset_sync: true` in YAML configuration
- Check that `offset_entity` and `temperature_sensor` entity IDs are correct
- Ensure external sensor is reporting valid temperature values
- Review logs for offset sync messages (search "offset sync" or "Auto-syncing")
- Increase `offset_hysteresis` if updates are too frequent

### Configure Button Shows Error 500
- This was a known issue in earlier versions, fixed in current release
- Restart Home Assistant after updating integration
- Check Home Assistant logs for specific error messages
- Report persistent issues with log traces

### Frontend "New Version Available" Loop
- This is typically a Lovelace custom card issue, not the integration
- Check browser console for JavaScript errors
- Look for duplicate resource entries in Settings → Dashboards → Resources
- See [Frontend Troubleshooting](#frontend-issues) section

---

## Development & Contributing

### Project Structure
```
custom_components/tado_x/
├── __init__.py          # Integration setup, services, YAML config
├── api.py              # Tado X API client (OAuth, endpoints)
├── binary_sensor.py    # Window, heating, connectivity sensors
├── climate.py          # Thermostat control entities
├── config_flow.py      # UI configuration flow
├── const.py            # Constants and configuration keys
├── coordinator.py      # Data update coordinator, offset sync logic
├── diagnostics.py      # Diagnostic data export
├── manifest.json       # Integration metadata
├── number.py           # Temperature offset number entities
├── sensor.py           # Temperature, humidity, battery sensors
├── services.yaml       # Service definitions
├── strings.json        # UI translations (English)
├── switch.py           # Boost mode and child lock switches
└── translations/
    └── en.json         # Entity translations
```

### Key Components
- **Coordinator:** Handles API polling, data caching, geofencing checks, and automatic offset synchronization
- **API Client:** OAuth device flow authentication, token refresh, all Tado X endpoints
- **Config Flow:** UI-based setup with OAuth device code flow and reauth support

### Testing Changes
1. Copy modified files to `config/custom_components/tado_x/`
2. Restart Home Assistant
3. Check logs: Settings → System → Logs
4. Enable debug logging:
   ```yaml
   logger:
     default: info
     logs:
       custom_components.tado_x: debug
   ```

---

## Known Issues & Limitations

### Current Limitations
- **Mobile app features not exposed:** Scheduling, away mode rules, and some advanced settings are only accessible via Tado mobile app or web interface
- **Boost mode duration:** Currently sets to default duration; custom duration not yet configurable
- **No schedule editing:** Schedules must be managed in Tado app
- **Window detection:** Read-only; cannot be manually triggered via integration

### Planned Enhancements
- Schedule viewing and editing
- Configurable boost duration
- More granular control over geofencing behavior
- Additional diagnostic sensors (API usage counter, last update time)

---

## Changelog

### v1.2.0 (Current - Enhanced Fork)
**New Features:**
- ✅ Geofencing with automatic HOME/AWAY switching
- ✅ Automatic temperature offset synchronization with external sensors
- ✅ Device temperature sensors (raw and offset-corrected)
- ✅ Boost mode switches per room
- ✅ Child lock switches per device
- ✅ Set presence service
- ✅ Enhanced attributes on all entities (firmware, mounting state, connection state)
- ✅ Full diagnostics support
- ✅ YAML configuration support with override priority

**Bug Fixes:**
- Fixed Configure button 500 error (Options flow property setter issue)
- Fixed integration reload loops on startup
- Fixed device temperature sensors not appearing for all device types
- Improved token refresh logic to prevent unnecessary refreshes
- **Fixed geofencing not updating sensor state automatically** - The presence sensor now correctly reflects the updated state after automatic HOME/AWAY switching

**API Improvements:**
- Added `set_room_boost()` for boost mode control
- Added `set_device_child_lock()` for child lock control
- Added `set_presence()` for manual HOME/AWAY control
- Enhanced `set_multiple_device_temperature_offsets()` for parallel updates

### v1.1.0 (Original by @exabird)
- Initial Tado X integration
- Basic climate control
- Temperature and humidity sensors
- OAuth device flow authentication
- Batch offset update service

---

## License

MIT License - see [LICENSE](LICENSE) file for details.

This project is a fork and enhancement of the original work by @exabird. Both the original project and this enhanced version are released under the MIT License.

---

## Support & Feedback

- **Issues:** Report bugs or request features via GitHub Issues
- **Discussions:** For questions and community support
- **Logs:** Always include relevant Home Assistant logs when reporting issues
- **Diagnostics:** Use the built-in diagnostics export for troubleshooting

---

## Acknowledgments

- **Original Author:** [@exabird](https://github.com/exabird) for the foundational ha-tado-x integration
- **Tado API:** Reverse-engineered Tado X API endpoints and authentication flow
- **Home Assistant Community:** For testing, feedback, and feature requests

