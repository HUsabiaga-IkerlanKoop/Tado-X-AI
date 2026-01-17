# Automatic Temperature Offset Synchronization - Integrated Solution

## What Changed

The temperature offset synchronization is now **fully integrated into the coordinator**. No separate automations needed!

## How It Works

1. **During each coordinator update cycle** (every `scan_interval` seconds):
   - Fetches room and device data from Tado API (1 API call)
   - Reads configured room sensor temperatures from Home Assistant
   - Calculates required offsets: `room_temp - valve_temp`
   - Updates offsets that exceed hysteresis threshold (N parallel API calls)

2. **Result**: All offset updates happen automatically within the same refresh cycle

## Configuration

Add to your `configuration.yaml`:

```yaml
tado_x:
  scan_interval: 1800  # 30 minutes
  auto_offset_sync: true
  offset_hysteresis: 0.5
  rooms:
    - offset_entity: number.egongela_va04_temperature_offset_2
      temperature_sensor: sensor.air_quality_egongela_temperature_2
    - offset_entity: number.logela_1_va04_temperature_offset
      temperature_sensor: sensor.air_quality_logela_1_temperature
```

**No device serial numbers needed!** Just use entity IDs that you can copy from the UI.

See [configuration_example.yaml](configuration_example.yaml) for complete example with all your rooms.

## API Call Efficiency

**Before (separate automations):**
- Integration polls: ~100 calls/day
- Offset automations: 50-100 additional calls/day
- **Total: 150-200 calls/day** ❌ (exceeds limit)

**After (integrated):**
- Integration polls + offset sync: 48 calls/day (30 min intervals)
- Each poll includes: 1 data fetch + N offset updates (only when needed)
- Hysteresis prevents unnecessary updates
- **Total: ~48-60 calls/day** ✅ (well within limit)

## Key Benefits

1. **Unified Operation**: Everything happens in one coordinator cycle
2. **No Automations Needed**: Configuration-driven, no YAML automations required
3. **Optimal API Usage**: Offsets sync only when coordinator refreshes
4. **Intelligent Updates**: Hysteresis prevents excessive API calls
5. **Predictable Timing**: Syncs exactly on scan_interval

## Finding Entity IDs (Easy!)

### Method 1: Entities Page (Recommended)
1. Settings → Devices & Services → Entities tab
2. **Filter by "offset"** to find your TRV offset entities
   - Example: `number.egongela_va04_temperature_offset`
3. Click the copy icon next to entity ID
4. **Filter by "temperature"** to find your room sensors
   - Example: `sensor.air_quality_egongela_temperature_2`
5. Copy those entity IDs

### Method 2: Developer Tools
1. Developer Tools → States
2. Search for "offset" - find `number.ROOM_va04_temperature_offset`
3. Search for your sensor - find `sensor.room_temperature`
4. Copy both entity IDs

**That's it!** No device serials, no digging through device info.

## Migration from Automation-Based System

1. **Remove old automations** (Automation.yaml, Automation_batch.yaml)
2. **Add configuration** to configuration.yaml (see example)
3. **Copy entity IDs** from Settings → Devices & Services → Entities
3. **Add configuration** to configuration.yaml (see example above)
4. **Restart Home Assistant**
5
## Recommended Settings

For 100 API calls/day limit:
```yaml
tado_x:
  scan_interval: 1800  # 30 minutes = 48 calls/day
  auto_offset_sync: true
  offset_hysteresis: 0.5  # Prevents micro-adjustments
```

For 20,000 API calls/day (with Auto-Assist):
```yaml
tado_x:
  scan_interval: 300  # 5 minutes = 288 calls/day  
  auto_offset_sync: true
  offset_hysteresis: 0.3  # More responsive
```

## Monitoring

Enable debug logging to monitor offset synchronization:

```yaml
logger:
  default: info
  logs:
    custom_components.tado_x.coordinator: debug
```

Look for log messages:
- "Auto-syncing X device offsets" - Updates being applied
- "Auto offset sync completed: X successful, Y failed" - Results
- "No offset updates needed" - All within hysteresis
- "Offset sync for SERIAL: room=X°C, valve=Y°C..." - Detailed calculations

## Troubleshooting

**Offsets not updating:**
- Verify device serial numbers are correct
- Check room sensor entity IDs exist and are available
- Ensure `auto_offset_sync: true` in configuration
- Check logs for error messages

**Too many API calls:**
- Increase `scan_interval` (e.g., 3600 = 1 hour)
- Increase `offset_hysteresis` (e.g., 0.8 or 1.0)
- Verify you're not running old automations simultaneously

**Offset fluctuations:**
- Increase `offset_hysteresis` to 0.8 or 1.0
- Verify room sensors are stable (not oscillating)
- Check valve sensors aren't affected by heating cycles

## Comparison: Integrated vs Automation Approaches

| Aspect | Old (Automations) | New (Integrated) |
|--------|-------------------|------------------|
| Configuration | Multiple YAML automations | Single config in configuration.yaml |
| API Calls | Unpredictable (on state change) | Predictable (on scan_interval) |
| Timing | Immediate on temp change | Synchronized with data refresh |
| Complexity | 5+ separate automations | Built-in feature |
| Maintenance | Update multiple files | Update one config |
| Call Efficiency | 150-250/day | 48-60/day |

## Advanced: Batch Service Still Available

The `tado_x.batch_update_temperature_offsets` service is still available for manual or custom automation use:

```yaml
service: tado_x.batch_update_temperature_offsets
data:
  offsets:
    "RU01234567890": 2.5
    "RU01234567891": -1.0
```

Use this for:
- One-time manual adjustments
- Custom automation logic
- External control systems
- Testing purposes

## Summary

✅ **Configuration-based** - No automations required  
✅ **Integrated** - Offsets sync during normal data refresh  
✅ **Efficient** - Minimal API calls, respects hysteresis  
✅ **Predictable** - Runs on fixed schedule  
✅ **Simple** - One config file to maintain
