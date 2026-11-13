"""Config flow: the address of hue-web (the service that owns the bridge connections)."""
from __future__ import annotations

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .api_client import ApiError, HueWebClient
from .const import CONF_URL, DEFAULT_URL, DOMAIN


class HueStudioConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            await self.async_set_unique_id(url)
            self._abort_if_unique_id_configured()
            try:
                await self.hass.async_add_executor_job(HueWebClient(url, timeout=8).get, "/healthz")
            except ApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="Hue Web", data={CONF_URL: url})
        schema = vol.Schema({vol.Required(CONF_URL, default=DEFAULT_URL): str})
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
