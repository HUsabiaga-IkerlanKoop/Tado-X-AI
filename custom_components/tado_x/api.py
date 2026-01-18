"""API client for Tado X."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp
import ssl

from .const import (
    TADO_AUTH_URL,
    TADO_CLIENT_ID,
    TADO_HOPS_API_URL,
    TADO_MY_API_URL,
    TADO_TOKEN_URL,
)

_LOGGER = logging.getLogger(__name__)


class TadoXAuthError(Exception):
    """Exception for authentication errors."""


class TadoXApiError(Exception):
    """Exception for API errors."""


class TadoXApi:
    """Tado X API client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str | None = None,
        refresh_token: str | None = None,
        token_expiry: datetime | None = None,
    ) -> None:
        """Initialize the API client."""
        self._session = session
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._token_expiry = token_expiry
        self._home_id: int | None = None

    @property
    def access_token(self) -> str | None:
        """Return the current access token."""
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        """Return the current refresh token."""
        return self._refresh_token

    @property
    def token_expiry(self) -> datetime | None:
        """Return the token expiry time."""
        return self._token_expiry

    @property
    def home_id(self) -> int | None:
        """Return the home ID."""
        return self._home_id

    @home_id.setter
    def home_id(self, value: int) -> None:
        """Set the home ID."""
        self._home_id = value

    async def start_device_auth(self) -> dict[str, Any]:
        """Start the device authorization flow.

        Returns a dict with device_code, user_code, verification_uri, etc.
        """
        _LOGGER.warning("Starting device authorization flow")
        timeout = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)

        # Use existing session but enforce timeout
        try:
            _LOGGER.warning("Sending request to %s", TADO_AUTH_URL)
            async with self._session.post(
                TADO_AUTH_URL,
                data={
                    "client_id": TADO_CLIENT_ID,
                    "scope": "offline_access",
                },
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Connection": "close",
                },
                timeout=timeout,
            ) as response:
                _LOGGER.warning("Device auth response status: %s", response.status)
                if response.status != 200:
                    text = await response.text()
                    _LOGGER.error("Failed to start device auth: %s - %s", response.status, text)
                    raise TadoXAuthError(f"Failed to start device auth: {response.status}")
                result = await response.json()
                _LOGGER.warning("Device auth successful, got user_code: %s", result.get("user_code"))
                return result
        except asyncio.TimeoutError as err:
            _LOGGER.error("Timeout during device auth request (30s)")
            raise TadoXAuthError("Timeout during device auth request") from err
        except aiohttp.ClientError as err:
            _LOGGER.error("Network error during device auth: %s (type: %s)", err, type(err).__name__)
            raise TadoXAuthError(f"Network error: {err}") from err
        except ssl.SSLError as err:
            _LOGGER.error("SSL error during device auth: %s", err)
            raise TadoXAuthError(f"SSL error: {err}") from err
        except Exception as err:
            _LOGGER.error("Unexpected error during device auth: %s (type: %s)", err, type(err).__name__)
            raise TadoXAuthError(f"Unexpected error: {err}") from err

    async def poll_for_token(self, device_code: str, interval: int = 5, timeout: int = 300) -> bool:
        """Poll for the access token after user authorizes.

        Returns True if successful, False if timed out.
        """
        start_time = datetime.now()
        while (datetime.now() - start_time).seconds < timeout:
            try:
                async with self._session.post(
                    TADO_TOKEN_URL,
                    data={
                        "client_id": TADO_CLIENT_ID,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                ) as response:
                    data = await response.json()

                    if response.status == 200:
                        self._access_token = data["access_token"]
                        self._refresh_token = data.get("refresh_token")
                        expires_in = data.get("expires_in", 600)
                        self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
                        return True

                    # Authorization pending, continue polling
                    if data.get("error") == "authorization_pending":
                        await asyncio.sleep(interval)
                        continue

                    # Other error
                    _LOGGER.error("Token error: %s", data)
                    raise TadoXAuthError(f"Token error: {data.get('error_description', data.get('error'))}")

            except aiohttp.ClientError as err:
                _LOGGER.error("Network error during token polling: %s", err)
                await asyncio.sleep(interval)

        return False

    async def refresh_access_token(self) -> bool:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            raise TadoXAuthError("No refresh token available")

        try:
            async with self._session.post(
                TADO_TOKEN_URL,
                data={
                    "client_id": TADO_CLIENT_ID,
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    _LOGGER.error("Failed to refresh token: %s - %s", response.status, text)
                    raise TadoXAuthError(f"Failed to refresh token: {response.status}")

                data = await response.json()
                self._access_token = data["access_token"]
                self._refresh_token = data.get("refresh_token", self._refresh_token)
                expires_in = data.get("expires_in", 600)
                # Use UTC for expiry to avoid timezone issues
                self._token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                return True

        except aiohttp.ClientError as err:
            raise TadoXAuthError(f"Network error during token refresh: {err}") from err

    async def ensure_valid_token(self) -> None:
        """Ensure we have a valid access token."""
        if not self._access_token:
            raise TadoXAuthError("Not authenticated")

        # Refresh if token expires in less than 60 seconds
        # Use UTC for comparison if we have expiry
        if self._token_expiry:
            now = datetime.now(timezone.utc)
            # Handle naive datetime if it was loaded from storage without timezone
            if self._token_expiry.tzinfo is None:
                # Assume standard datetime.now() (system local) was used before
                # Convert system local 'now' to aware UTC is complex without libs
                # Fallback: compare with naive now
                now = datetime.now()
            
            if now >= self._token_expiry - timedelta(seconds=60):
                await self.refresh_access_token()

    async def _request(
        self,
        method: str,
        url: str,
        json_data: dict | None = None,
    ) -> dict | list | None:
        """Make an authenticated API request."""
        await self.ensure_valid_token()

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_data,
            ) as response:
                if response.status == 401:
                    # Try to refresh token and retry
                    await self.refresh_access_token()
                    headers["Authorization"] = f"Bearer {self._access_token}"
                    async with self._session.request(
                        method,
                        url,
                        headers=headers,
                        json=json_data,
                    ) as retry_response:
                        if retry_response.status != 200:
                            text = await retry_response.text()
                            raise TadoXApiError(f"API error: {retry_response.status} - {text}")
                        if retry_response.content_length == 0:
                            return None
                        return await retry_response.json()

                if response.status not in (200, 204):
                    text = await response.text()
                    raise TadoXApiError(f"API error: {response.status} - {text}")

                if response.content_length == 0 or response.status == 204:
                    return None
                return await response.json()

        except aiohttp.ClientError as err:
            raise TadoXApiError(f"Network error: {err}") from err

    # My Tado API endpoints (user info)
    async def get_me(self) -> dict[str, Any]:
        """Get user information including homes."""
        result = await self._request("GET", f"{TADO_MY_API_URL}/me")
        return result if isinstance(result, dict) else {}

    async def get_homes(self) -> list[dict[str, Any]]:
        """Get list of homes for the user."""
        me = await self.get_me()
        return me.get("homes", [])

    async def get_home_state(self) -> dict[str, Any]:
        """Get the presence state of the home."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")
        result = await self._request("GET", f"{TADO_MY_API_URL}/homes/{self._home_id}/state")
        return result if isinstance(result, dict) else {}

    async def get_mobile_devices(self) -> list[dict[str, Any]]:
        """Get all mobile devices for the home."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")
        result = await self._request("GET", f"{TADO_MY_API_URL}/homes/{self._home_id}/mobileDevices")
        return result if isinstance(result, list) else []

    async def set_presence(self, presence: str) -> None:
        """Set the home presence (HOME or AWAY)."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")
        await self._request("PUT", f"{TADO_MY_API_URL}/homes/{self._home_id}/presence", json_data={"presence": presence})

    # Hops Tado API endpoints (Tado X specific)
    async def get_rooms(self) -> list[dict[str, Any]]:
        """Get all rooms with current state."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")
        result = await self._request("GET", f"{TADO_HOPS_API_URL}/homes/{self._home_id}/rooms")
        return result if isinstance(result, list) else []

    async def get_rooms_and_devices(self) -> dict[str, Any]:
        """Get all rooms with their devices."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")
        result = await self._request("GET", f"{TADO_HOPS_API_URL}/homes/{self._home_id}/roomsAndDevices")
        return result if isinstance(result, dict) else {}

    async def set_room_temperature(
        self,
        room_id: int,
        temperature: float,
        power: str = "ON",
        termination_type: str = "TIMER",
        duration_seconds: int = 1800,
    ) -> None:
        """Set the temperature for a room."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        data: dict[str, Any] = {
            "setting": {
                "power": power,
                "temperature": {"value": temperature},
            },
            "termination": {"type": termination_type},
        }

        if termination_type == "TIMER":
            data["termination"]["durationInSeconds"] = duration_seconds

        await self._request(
            "POST",
            f"{TADO_HOPS_API_URL}/homes/{self._home_id}/rooms/{room_id}/manualControl",
            json_data=data,
        )

    async def set_room_off(
        self,
        room_id: int,
        termination_type: str = "TIMER",
        duration_seconds: int = 1800,
    ) -> None:
        """Turn off heating for a room (frost protection mode)."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        data: dict[str, Any] = {
            "setting": {
                "power": "OFF",
            },
            "termination": {"type": termination_type},
        }

        if termination_type == "TIMER":
            data["termination"]["durationInSeconds"] = duration_seconds

        _LOGGER.debug("Setting room %s to OFF with data: %s", room_id, data)

        result = await self._request(
            "POST",
            f"{TADO_HOPS_API_URL}/homes/{self._home_id}/rooms/{room_id}/manualControl",
            json_data=data,
        )

        _LOGGER.debug("Set room OFF response: %s", result)

    async def resume_schedule(self, room_id: int) -> None:
        """Resume the schedule for a room (cancel manual control)."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        await self._request(
            "DELETE",
            f"{TADO_HOPS_API_URL}/homes/{self._home_id}/rooms/{room_id}/manualControl",
        )

    async def set_boost_mode(self, room_id: int | None = None) -> None:
        """Activate boost mode for a room or all rooms."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        if room_id:
            await self._request(
                "POST",
                f"{TADO_HOPS_API_URL}/homes/{self._home_id}/rooms/{room_id}/boost",
            )
        else:
            await self._request(
                "POST",
                f"{TADO_HOPS_API_URL}/homes/{self._home_id}/quickActions/boost",
            )

    async def resume_all_schedules(self) -> None:
        """Resume schedule for all rooms."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        await self._request(
            "POST",
            f"{TADO_HOPS_API_URL}/homes/{self._home_id}/quickActions/resumeSchedule",
        )

    async def set_open_window_detection(self, room_id: int, enabled: bool) -> None:
        """Enable or disable open window detection for a room."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        if enabled:
            await self._request(
                "POST",
                f"{TADO_HOPS_API_URL}/homes/{self._home_id}/rooms/{room_id}/openWindow",
            )
        else:
            await self._request(
                "DELETE",
                f"{TADO_HOPS_API_URL}/homes/{self._home_id}/rooms/{room_id}/openWindow",
            )

    async def set_device_temperature_offset(self, device_serial: str, offset: float) -> None:
        """Set the temperature offset for a device (VA04 or SU04 only)."""
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        await self._request(
            "PATCH",
            f"{TADO_HOPS_API_URL}/homes/{self._home_id}/roomsAndDevices/devices/{device_serial}",
            json_data={"temperatureOffset": offset},
        )

    async def set_multiple_device_temperature_offsets(
        self, offsets: dict[str, float]
    ) -> dict[str, str]:
        """Set temperature offsets for multiple devices in parallel.
        
        This method makes parallel API calls to update multiple device offsets simultaneously.
        While this doesn't reduce the total number of API calls, it updates all devices
        during a single coordinator refresh cycle.
        
        Args:
            offsets: Dictionary mapping device serial numbers to offset values
                    e.g., {"serial1": 2.5, "serial2": -1.0}
        
        Returns:
            Dictionary mapping device serial numbers to status ("success" or error message)
        """
        if not self._home_id:
            raise TadoXApiError("Home ID not set")

        results: dict[str, str] = {}
        
        async def set_single_offset(serial: str, offset: float) -> tuple[str, str]:
            """Set offset for a single device and return result."""
            try:
                await self._request(
                    "PATCH",
                    f"{TADO_HOPS_API_URL}/homes/{self._home_id}/roomsAndDevices/devices/{serial}",
                    json_data={"temperatureOffset": offset},
                )
                return (serial, "success")
            except Exception as err:
                _LOGGER.error("Failed to set offset for device %s: %s", serial, err)
                return (serial, f"error: {err}")

        # Execute all offset updates in parallel
        tasks = [set_single_offset(serial, offset) for serial, offset in offsets.items()]
        task_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Build results dictionary
        for result in task_results:
            if isinstance(result, tuple):
                serial, status = result
                results[serial] = status
            elif isinstance(result, Exception):
                _LOGGER.error("Task failed with exception: %s", result)
        
        return results
