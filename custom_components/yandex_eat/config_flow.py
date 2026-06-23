from __future__ import annotations

import logging
from functools import lru_cache

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import CONF_SCAN_INTERVAL, CONF_X_TOKEN, CONF_RESTAURANT_AS, DEFAULT_SCAN_INTERVAL, DEFAULT_RESTAURANT_AS, DOMAIN, RESTAURANT_AS_MARKET
from .yandex_session import LoginResponse, YandexSession

_LOGGER = logging.getLogger(__name__)


def generate_qr_code(data: str) -> str:
    try:
        from homeassistant.auth.mfa_modules import totp

        # noinspection PyProtectedMember
        return totp._generate_qr_code(data)
    except Exception as err:
        return repr(err)


class YandexEatConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @property
    @lru_cache(maxsize=1)
    def yandex(self) -> YandexSession:
        session = async_create_clientsession(self.hass)
        return YandexSession(session)

    async def async_step_user(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {
                        vol.Required("method", default="qr"): vol.In(
                            {
                                "qr": "QR-код",
                                "token": "Токен",
                            }
                        )
                    }
                ),
            )

        if user_input["method"] == "qr":
            qr_url = await self.yandex.get_qr()
            return self.async_show_form(
                step_id="qr",
                description_placeholders={
                    "qr_url": qr_url,
                    "qr_data": generate_qr_code(qr_url),
                },
            )

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required("token"): str}),
        )

    async def async_step_qr(self, user_input: dict | None = None) -> ConfigFlowResult:
        resp = await self.yandex.login_qr()
        if not resp:
            return self.async_show_form(step_id="qr", errors={"base": "unauthorised"})
        return await self._check_yandex_response(resp)

    async def async_step_token(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="token",
                data_schema=vol.Schema({vol.Required("token"): str}),
            )
        resp = await self.yandex.validate_token(user_input["token"].strip())
        return await self._check_yandex_response(resp)

    async def async_step_reauth(self, entry_data: dict) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({vol.Required("token"): str}),
            )
        session = async_create_clientsession(self.hass)
        resp = await YandexSession(session).validate_token(user_input["token"].strip())
        if not resp.ok:
            return self.async_show_form(step_id="reauth_confirm", errors={"base": resp.error})
        reauth_entry = self._get_reauth_entry()
        self.hass.config_entries.async_update_entry(
            reauth_entry,
            data={**reauth_entry.data, CONF_X_TOKEN: resp.x_token},
        )
        await self.hass.config_entries.async_reload(reauth_entry.entry_id)
        return self.async_abort(reason="reauth_successful")

    async def _check_yandex_response(self, resp: LoginResponse) -> ConfigFlowResult:
        if resp.ok:
            await self.async_set_unique_id(resp.display_login)
            self._abort_if_unique_id_configured(
                updates={CONF_X_TOKEN: resp.x_token},
                reload_on_update=True,
            )
            return self.async_create_entry(
                title=resp.display_login,
                data={CONF_X_TOKEN: resp.x_token},
            )

        if resp.errors:
            _LOGGER.debug("Yandex auth error: %s", resp.error)
            if self.context.get("source") == "reauth":
                return self.async_show_form(step_id="reauth_confirm", errors={"base": resp.error})
            step_id = "token" if self.context.get("step_id") == "token" else "qr"
            return self.async_show_form(step_id=step_id, errors={"base": resp.error})

        raise AbortFlow("not_implemented")

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return YandexEatOptionsFlowHandler()


class YandexEatOptionsFlowHandler(OptionsFlow):
    async def async_step_init(self, user_input: dict | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = dict(self.config_entry.options)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=15, max=300)),
                    vol.Optional(
                        CONF_RESTAURANT_AS,
                        default=options.get(CONF_RESTAURANT_AS, DEFAULT_RESTAURANT_AS),
                    ): vol.In(
                        {
                            DEFAULT_RESTAURANT_AS: "Еда (рестораны в счётчике Еда)",
                            RESTAURANT_AS_MARKET: "Деливери (рестораны в счётчике Деливери)",
                        }
                    ),
                }
            ),
        )
