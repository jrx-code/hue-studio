"""Config flow: the address of hue-web (the service that owns the bridge connections); reconfigure changes it in place."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api_client import ApiError, HueWebClient
from .const import CONF_URL, DEFAULT_URL, DOMAIN


async def _reachable(hass, url: str) -> str | None:
    """None when hue-web answers /healthz, else the error key of the form."""
    try:
        client = HueWebClient(url, timeout=8)            # refuses anything but http(s) before any request
        await hass.async_add_executor_job(client.get, "/healthz")
    except ApiError as exc:
        return "invalid_url" if exc.status == 400 else "cannot_connect"
    return None


class HueStudioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()
            if (err := await _reachable(self.hass, url)) is None:
                return self.async_create_entry(title="Hue Web", data={CONF_URL: url})
            errors["base"] = err
        schema = vol.Schema({vol.Required(CONF_URL, default=DEFAULT_URL): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict | None = None) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            if (err := await _reachable(self.hass, url)) is None:
                await self.async_set_unique_id(url)
                return self.async_update_reload_and_abort(entry, unique_id=url, data_updates={CONF_URL: url})
            errors["base"] = err
        schema = vol.Schema({vol.Required(CONF_URL, default=entry.data.get(CONF_URL, DEFAULT_URL)): str})
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
