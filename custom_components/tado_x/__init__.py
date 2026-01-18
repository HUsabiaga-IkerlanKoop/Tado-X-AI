"""The Tado X integration."""
from __future__ import annotations

import logging
from datetime import datetime

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TadoXApi, TadoXApiError, TadoXAuthError
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_HOME_ID,
    CONF_HOME_NAME,
    CONF_REFRESH_TOKEN,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN_EXPIRY,
    CONF_GEOFENCING_ENABLED,
    CONF_MIN_TEMP,
    CONF_MAX_TEMP,
    CONF_AUTO_OFFSET_SYNC,
    CONF_ROOMS,
    CONF_OFFSET_ENTITY,
    CONF_TEMPERATURE_SENSOR,
    CONF_OFFSET_HYSTERESIS,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_OFFSET_HYSTERESIS,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import TadoXDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    cv.positive_int, vol.Range(min=30, max=3600)
                ),
                vol.Optional(CONF_GEOFENCING_ENABLED, default=False): cv.boolean,
                vol.Optional(CONF_AUTO_OFFSET_SYNC, default=False): cv.boolean,
                vol.Optional(CONF_OFFSET_HYSTERESIS, default=DEFAULT_OFFSET_HYSTERESIS): vol.Coerce(float),
                vol.Optional(CONF_ROOMS, default=[]): vol.All(
                    cv.ensure_list,
                    [
                        vol.Schema(
                            {
                                vol.Required(CONF_OFFSET_ENTITY): cv.entity_id,
                                vol.Required(CONF_TEMPERATURE_SENSOR): cv.entity_id,
                            }
                        )
                    ],
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tado X component from YAML."""
    hass.data.setdefault(DOMAIN, {})
    
    # Store YAML config for later use
    if DOMAIN in config:
        hass.data[DOMAIN]["yaml_config"] = config[DOMAIN]
    
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tado X from a config entry."""
    session = async_get_clientsession(hass)

    # Parse token expiry
    token_expiry = None
    if entry.data.get(CONF_TOKEN_EXPIRY):
        try:
            token_expiry = datetime.fromisoformat(entry.data[CONF_TOKEN_EXPIRY])
        except (ValueError, TypeError):
            pass

    api = TadoXApi(
        session=session,
        access_token=entry.data.get(CONF_ACCESS_TOKEN),
        refresh_token=entry.data.get(CONF_REFRESH_TOKEN),
        token_expiry=token_expiry,
    )

    home_id = entry.data[CONF_HOME_ID]
    home_name = entry.data.get(CONF_HOME_NAME, f"Tado Home {home_id}")

    # Ensure token is valid (refresh if needed)
    try:
        old_access_token = api.access_token
        old_expiry = api.token_expiry
        
        await api.ensure_valid_token()

        # Update stored tokens ONLY if changed
        if api.access_token != old_access_token or api.token_expiry != old_expiry:
            _LOGGER.debug("Token refreshed during setup, updating config entry")
            hass.config_entries.async_update_entry(
                entry,
                data={
                    **entry.data,
                    CONF_ACCESS_TOKEN: api.access_token,
                    CONF_REFRESH_TOKEN: api.refresh_token,
                    CONF_TOKEN_EXPIRY: api.token_expiry.isoformat() if api.token_expiry else None,
                },
            )
    except TadoXAuthError as err:
        _LOGGER.error("Authentication failed: %s", err)
        raise ConfigEntryAuthFailed(f"Authentication failed: {err}") from err

    # Get scan interval - YAML config overrides stored value and options
    yaml_config = hass.data[DOMAIN].get("yaml_config", {})
    scan_interval = yaml_config.get(
        CONF_SCAN_INTERVAL,
        entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        )
    )
    _LOGGER.info("Using scan interval: %s seconds", scan_interval)
    
    # Get offset sync configuration from YAML
    auto_offset_sync = yaml_config.get(CONF_AUTO_OFFSET_SYNC, False)
    room_configs = yaml_config.get(CONF_ROOMS, [])
    offset_hysteresis = yaml_config.get(CONF_OFFSET_HYSTERESIS, DEFAULT_OFFSET_HYSTERESIS)
    
    # Get geofencing configuration - YAML config overrides stored value and options
    geofencing_enabled = yaml_config.get(
        CONF_GEOFENCING_ENABLED,
        entry.options.get(
            CONF_GEOFENCING_ENABLED,
            entry.data.get(CONF_GEOFENCING_ENABLED, False)
        )
    )
    
    if auto_offset_sync and room_configs:
        _LOGGER.info("Auto offset sync enabled with %d room configurations", len(room_configs))

    # Ensure home device exists before platforms/entities reference via_device
    from homeassistant.helpers import device_registry as dr
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, str(home_id))},
        name=home_name,
        manufacturer="Tado",
        model="Tado X Home",
    )

    # Create coordinator
    coordinator = TadoXDataUpdateCoordinator(
        hass=hass,
        api=api,
        home_id=home_id,
        home_name=home_name,
        scan_interval=scan_interval,
        geofencing_enabled=geofencing_enabled,
        min_temp=entry.options.get(
            CONF_MIN_TEMP,
            entry.data.get(CONF_MIN_TEMP)
        ),
        max_temp=entry.options.get(
            CONF_MAX_TEMP,
            entry.data.get(CONF_MAX_TEMP)
        ),
        auto_offset_sync=auto_offset_sync,
        room_configs=room_configs,
        offset_hysteresis=offset_hysteresis,
    )

    # Fetch initial data
    try:
        await coordinator.async_config_entry_first_refresh()
    except TadoXApiError as err:
        raise ConfigEntryNotReady(f"Failed to fetch data: {err}") from err

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Register batch offset update service
    async def async_batch_update_offsets(call: ServiceCall) -> None:
        """Handle batch temperature offset update service call."""
        offsets = call.data.get("offsets", {})
        
        if not offsets:
            _LOGGER.warning("No offsets provided to batch update service")
            return
        
        _LOGGER.info("Batch offset update service called with %d devices", len(offsets))
        results = await coordinator.async_batch_update_temperature_offsets(offsets)
        
        # Log results
        success_count = sum(1 for status in results.values() if status == "success")
        _LOGGER.info(
            "Batch offset update completed: %d successful, %d failed out of %d total",
            success_count,
            len(results) - success_count,
            len(results),
        )
        
        for device_serial, status in results.items():
            if status != "success":
                _LOGGER.error("Failed to update offset for device %s: %s", device_serial, status)

    # Register the service only once (for the first entry)
    if not hass.services.has_service(DOMAIN, "batch_update_temperature_offsets"):
        hass.services.async_register(
            DOMAIN,
            "batch_update_temperature_offsets",
            async_batch_update_offsets,
            schema=vol.Schema({
                vol.Required("offsets"): vol.Schema({
                    cv.string: vol.All(vol.Coerce(float), vol.Range(min=-9.9, max=9.9))
                })
            }),
        )
        _LOGGER.info("Registered batch_update_temperature_offsets service")

    # Store options for comparison in update listener
    hass.data[DOMAIN][entry.entry_id].last_options = entry.options.copy()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update options."""
    # Check if options actually changed
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator and hasattr(coordinator, "last_options"):
        if coordinator.last_options == entry.options:
            _LOGGER.debug("Options have not changed, ignoring update (probably data/token update)")
            return

    await hass.config_entries.async_reload(entry.entry_id)

