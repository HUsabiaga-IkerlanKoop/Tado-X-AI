# Batch Temperature Offset Update Feature

## Overview

This modification adds a **batch temperature offset update** feature to the Tado X integration, allowing multiple device offsets to be updated in parallel during a single coordinator refresh cycle.

## Problem Solved

**Original Issue:** Each `number.set_value` call for temperature offset consumed 1 API call. With 5 rooms and frequent updates, this quickly exceeded the 100 API calls/day limit for users without Auto-Assist subscription.

**Solution:** Batch all offset updates into a single operation that executes in parallel, minimizing API consumption.

## Changes Made

### 1. API Layer (`api.py`)
Added `async_set_multiple_device_temperature_offsets()` method that:
- Accepts a dictionary of device serials → offset values
- Executes all updates in parallel using `asyncio.gather()`
- Returns status for each device update
- Still makes N API calls, but executes them simultaneously

### 2. Coordinator (`coordinator.py`)
Added `async_batch_update_temperature_offsets()` method that:
- Calls the batch API method
- Triggers a coordinator refresh after updates
- Provides a centralized interface for batch operations

### 3. Integration Setup (`__init__.py`)
Registered new service `tado_x.batch_update_temperature_offsets`:
- Accepts `offsets` parameter (dict of serial → offset)
- Validates offset range (-9.9 to 9.9°C)
- Logs success/failure for each device

### 4. Service Definition (`services.yaml`)
Documents the service for Home Assistant UI

### 5. Example Automation (`Automation_batch.yaml`)
Demonstrates batch offset updates:
- Runs once per hour
- Calculates offsets for all rooms
- Updates only devices exceeding hysteresis threshold
- Uses single service call for all updates

## API Call Reduction

**Before:**
- 5 separate automations
- Each triggers on temperature changes
- 30-50 updates/day × 5 rooms = **150-250 API calls/day** ❌

**After (with batch service):**
- 1 automation running hourly
- 24 updates/day
- Each update: N API calls (N = number of devices needing update)
- Average: **24-60 API calls/day** for offsets ✅
- Leaves 40-76 calls for integration polling

## Usage

### Method 1: Use the Batch Automation

1. Copy `Automation_batch.yaml` to your Home Assistant automations
2. **IMPORTANT:** Replace device serial numbers with your actual device serials
   - Find serials in Developer Tools → States
   - Look for entities like `number.ROOM_va04_temperature_offset`
   - Serial is in the device info
3. Adjust `hours` in trigger (default: every hour)
4. Configure your sensor entity IDs

### Method 2: Call Service Directly

From Developer Tools → Services:

```yaml
service: tado_x.batch_update_temperature_offsets
data:
  offsets:
    RU01234567890: 2.5
    RU09876543210: -1.0
    RU01111111111: 0.5
```

### Method 3: Python Script/Automation

```yaml
- action: tado_x.batch_update_temperature_offsets
  data:
    offsets: >
      {% set offsets = {} %}
      {% for device in state_attr('sensor.tado_devices', 'devices') %}
        {# Your offset calculation logic here #}
      {% endfor %}
      {{ offsets }}
```

## Finding Device Serial Numbers

**Option 1 - From Entity:**
1. Go to Developer Tools → States
2. Find entities like `number.ROOM_va04_temperature_offset`
3. Click on the entity
4. Look in Device info for Serial Number

**Option 2 - From Integration:**
1. Settings → Devices & Services → Tado X
2. Click on a device
3. Serial number shown in device information

**Option 3 - From Logs:**
Enable debug logging:
```yaml
logger:
  logs:
    custom_components.tado_x: debug
```
Check logs for device serial numbers during startup.

## Integration Scan Interval

Since offset updates are now batched and run hourly, you can optimize the integration polling:

```yaml
# configuration.yaml
tado_x:
  scan_interval: 1800  # 30 minutes (48 calls/day)
```

## API Call Budget

With recommended settings:
- Integration polling (30 min): **48 calls/day**
- Batch offset updates (hourly): **24-40 calls/day** (depends on how many devices need updates)
- **Total: 72-88 calls/day** (within 100 limit) ✅

## Testing

1. Enable debug logging
2. Run the automation manually
3. Check logs for:
   ```
   Batch updating X device temperature offsets
   Batch offset update completed: X successful, Y failed out of Z total
   ```
4. Verify offsets updated in device entities

## Troubleshooting

**Service not found:**
- Restart Home Assistant after installing the modified integration
- Check integration loaded: Settings → Devices & Services → Tado X

**Offsets not updating:**
- Verify device serial numbers are correct
- Check hysteresis threshold (default 0.5°C)
- Enable debug logging to see calculations

**API limit still exceeded:**
- Reduce batch update frequency (e.g., every 2 hours)
- Increase integration scan_interval
- Check for other automations calling Tado services

## Compatibility

- **Home Assistant:** 2024.1.0+
- **Tado X Integration:** 1.1.0+
- **Backward Compatible:** Yes, existing single offset updates still work

## Future Improvements

1. Automatic serial number detection from coordinator data
2. Configuration UI for batch automation
3. Service to calculate offsets (pass room/valve sensor entities)
4. Optimistic state updates (show new offset before API confirms)

## Support

For issues or questions:
1. Check Home Assistant logs with debug enabled
2. Open issue on GitHub repository
3. Verify you're using latest integration version
