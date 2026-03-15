from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence
from urllib.parse import quote, urlencode
from uuid import uuid4

import httpx

from app.core.config import get_settings
from app.db.models import ProviderType
from app.integrations.base import DeviceProvider, ProviderDevice, ProviderEnergySample, ProviderStatusSnapshot

_EMPTY_BODY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
_SCALE_FALLBACKS = {
    "add_ele": {"scale": 3, "unit": "kW·h"},
    "cur_power": {"scale": 1, "unit": "W"},
    "cur_voltage": {"scale": 1, "unit": "V"},
    "cur_current": {"scale": 0, "unit": "mA"},
}


class TuyaApiError(RuntimeError):
    pass


@dataclass(slots=True)
class TuyaStatusDefinition:
    code: str
    scale: int = 0
    unit: str | None = None


class TuyaCloudProvider(DeviceProvider):
    provider_name = ProviderType.TUYA_CLOUD

    def __init__(self) -> None:
        settings = get_settings()
        access_id = settings.smartlife_tuya_access_id.strip()
        access_secret = settings.smartlife_tuya_access_secret.strip()
        if not access_id or not access_secret:
            raise ValueError(
                "Tuya Cloud provider is selected, but secrets/smartlife_tuya_access_id or secrets/smartlife_tuya_access_secret are empty."
            )
        self.client = TuyaOpenApiClient(
            base_url=settings.smartlife_tuya_base_url,
            access_id=access_id,
            access_secret=access_secret,
        )
        self._device_cache: list[dict[str, Any]] | None = None
        self._spec_cache: dict[str, dict[str, TuyaStatusDefinition]] = {}

    def get_devices(self) -> list[ProviderDevice]:
        devices = self.client.list_project_devices()
        self._device_cache = devices
        items: list[ProviderDevice] = []
        for raw in devices:
            name = raw.get("customName") or raw.get("name") or raw.get("id")
            last_seen = _timestamp_seconds_to_datetime(raw.get("updateTime") or raw.get("activeTime") or raw.get("createTime"))
            notes = f"Tuya Cloud · product={raw.get('productName') or 'unknown'} · category={raw.get('category') or 'unknown'}"
            items.append(
                ProviderDevice(
                    external_id=str(raw["id"]),
                    provider=self.provider_name,
                    name=name,
                    model=raw.get("productName") or None,
                    product_id=raw.get("productId") or None,
                    product_name=raw.get("productName") or None,
                    category=raw.get("category") or None,
                    location_name="Tuya Cloud",
                    icon_url=_normalize_icon(raw.get("icon")),
                    is_online=bool(raw.get("isOnline")),
                    last_seen_at=last_seen,
                    notes=notes,
                )
            )
        return items

    def get_daily_energy_samples(self) -> list[ProviderEnergySample]:
        return []

    def get_monthly_energy_samples(self) -> list[ProviderEnergySample]:
        return []

    def get_status_snapshots(self, devices: Sequence[ProviderDevice]) -> list[ProviderStatusSnapshot]:
        snapshots: list[ProviderStatusSnapshot] = []
        for device in devices:
            spec = self._get_spec_map(device.external_id)
            statuses = self.client.get_device_status(device.external_id)
            snapshots.append(self._build_snapshot(device.external_id, statuses, spec))
        return snapshots

    def _get_spec_map(self, device_id: str) -> dict[str, TuyaStatusDefinition]:
        cached = self._spec_cache.get(device_id)
        if cached is not None:
            return cached

        response = self.client.get_device_specification(device_id)
        definitions: dict[str, TuyaStatusDefinition] = {}
        for row in response.get("status", []):
            code = row.get("code")
            if not code:
                continue
            parsed_values = _parse_json_object(row.get("values"))
            fallback = _SCALE_FALLBACKS.get(code, {})
            definitions[code] = TuyaStatusDefinition(
                code=code,
                scale=int(parsed_values.get("scale", fallback.get("scale", 0)) or 0),
                unit=parsed_values.get("unit") or fallback.get("unit"),
            )
        self._spec_cache[device_id] = definitions
        return definitions

    def send_switch_command(self, device_id: str, switch_on: bool) -> dict[str, Any]:
        spec = self._get_spec_map(device_id)
        if "switch_1" not in spec:
            raise TuyaApiError(f"Device {device_id} does not expose switch_1 control via Tuya Cloud.")
        return self.client.send_device_commands(device_id, [{"code": "switch_1", "value": bool(switch_on)}])

    def _build_snapshot(
        self,
        device_id: str,
        statuses: list[dict[str, Any]],
        spec_map: dict[str, TuyaStatusDefinition],
    ) -> ProviderStatusSnapshot:
        status_map = {item.get("code"): item.get("value") for item in statuses if item.get("code")}
        switch_on = None
        for code, value in status_map.items():
            if code.startswith("switch_") and isinstance(value, bool):
                switch_on = value
                break

        power_w = _scaled_decimal(status_map.get("cur_power"), spec_map.get("cur_power"))
        voltage_v = _scaled_decimal(status_map.get("cur_voltage"), spec_map.get("cur_voltage"))
        energy_total_kwh = _scaled_decimal(status_map.get("add_ele"), spec_map.get("add_ele"))
        current_raw = _scaled_decimal(status_map.get("cur_current"), spec_map.get("cur_current"))
        current_a = None
        if current_raw is not None:
            current_a = (current_raw / Decimal("1000")).quantize(Decimal("0.001"))

        fault_value = status_map.get("fault")
        fault_code = None if fault_value in (None, "", 0, "0") else str(fault_value)

        return ProviderStatusSnapshot(
            external_id=device_id,
            recorded_at=datetime.utcnow().replace(microsecond=0),
            switch_on=switch_on,
            power_w=power_w,
            voltage_v=voltage_v,
            current_a=current_a,
            energy_total_kwh=energy_total_kwh,
            fault_code=fault_code or "0",
            source_note="tuya cloud status",
            raw_payload=json.dumps(statuses, ensure_ascii=False, sort_keys=True),
        )


class TuyaOpenApiClient:
    def __init__(self, base_url: str, access_id: str, access_secret: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_id = access_id
        self.access_secret = access_secret
        self.timeout = timeout
        self._access_token: str | None = None

    def list_project_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        last_id: str | None = None
        while True:
            params: dict[str, Any] = {"page_size": 20}
            if last_id:
                params["last_id"] = last_id
            payload = self._request_json("GET", "/v2.0/cloud/thing/device", params=params)
            batch = payload.get("result") or []
            if not isinstance(batch, list):
                raise TuyaApiError("Unexpected device list payload from Tuya.")
            if not batch:
                break
            devices.extend(batch)
            if len(batch) < 20:
                break
            next_last_id = batch[-1].get("id")
            if not next_last_id or next_last_id == last_id:
                break
            last_id = str(next_last_id)
        return devices

    def get_device_specification(self, device_id: str) -> dict[str, Any]:
        payload = self._request_json("GET", f"/v1.0/iot-03/devices/{quote(device_id, safe='')}/specification")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise TuyaApiError(f"Unexpected specification payload for device {device_id}.")
        return result

    def get_device_status(self, device_id: str) -> list[dict[str, Any]]:
        payload = self._request_json("GET", f"/v1.0/iot-03/devices/{quote(device_id, safe='')}/status")
        result = payload.get("result") or []
        if not isinstance(result, list):
            raise TuyaApiError(f"Unexpected status payload for device {device_id}.")
        return result

    def send_device_commands(self, device_id: str, commands: list[dict[str, Any]]) -> dict[str, Any]:
        payload = self._request_json(
            "POST",
            f"/v1.0/iot-03/devices/{quote(device_id, safe='')}/commands",
            body={"commands": commands},
        )
        result = payload.get("result")
        if not isinstance(result, dict):
            return {"success": True, "result": result}
        return result

    def _get_access_token(self) -> str:
        if self._access_token:
            return self._access_token
        payload = self._request_json("GET", "/v1.0/token", params={"grant_type": 1}, include_token=False)
        result = payload.get("result") or {}
        token = result.get("access_token")
        if not token:
            raise TuyaApiError("Tuya token response did not include access_token.")
        self._access_token = str(token)
        return self._access_token

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        include_token: bool = True,
        retry_on_auth: bool = True,
    ) -> dict[str, Any]:
        method = method.upper()
        params = params or {}
        body = body or {}
        access_token = self._get_access_token() if include_token else None
        headers = self._build_headers(method, path, params=params, body=body, access_token=access_token)
        url = f"{self.base_url}{path}"
        response = httpx.request(method, url, params=params, json=body or None, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if payload.get("success") is True:
            return payload

        code = str(payload.get("code", ""))
        message = payload.get("msg") or payload.get("message") or "Unknown Tuya API error"
        if include_token and retry_on_auth and code in {"1010", "1011", "1106", "2406"}:
            self._access_token = None
            return self._request_json(
                method,
                path,
                params=params,
                body=body,
                include_token=include_token,
                retry_on_auth=False,
            )
        raise TuyaApiError(f"Tuya API request failed: code={code or 'n/a'} message={message}")

    def _build_headers(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any],
        body: dict[str, Any],
        access_token: str | None,
    ) -> dict[str, str]:
        t = str(int(datetime.now(tz=timezone.utc).timestamp() * 1000))
        nonce = uuid4().hex
        body_text = json.dumps(body, separators=(",", ":"), ensure_ascii=False) if body else ""
        body_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest() if body_text else _EMPTY_BODY_SHA256
        canonical_url = _build_canonical_url(path, params)
        string_to_sign = f"{method}\n{body_hash}\n\n{canonical_url}"
        payload = f"{self.access_id}{access_token or ''}{t}{nonce}{string_to_sign}"
        sign = hmac.new(self.access_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest().upper()

        headers = {
            "client_id": self.access_id,
            "sign": sign,
            "sign_method": "HMAC-SHA256",
            "t": t,
            "nonce": nonce,
            "Content-Type": "application/json",
        }
        if access_token:
            headers["access_token"] = access_token
        return headers



def _build_canonical_url(path: str, params: dict[str, Any]) -> str:
    clean_items: list[tuple[str, str]] = []
    for key, value in params.items():
        if value is None:
            continue
        clean_items.append((str(key), str(value)))
    clean_items.sort(key=lambda item: item[0])
    if not clean_items:
        return path
    query_string = urlencode(clean_items, quote_via=quote, safe=",")
    return f"{path}?{query_string}"



def _parse_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}



def _scaled_decimal(value: Any, definition: TuyaStatusDefinition | None) -> Decimal | None:
    if value is None or value == "":
        return None
    scale = definition.scale if definition else 0
    try:
        decimal_value = Decimal(str(value))
    except Exception:
        return None
    divisor = Decimal(10) ** scale
    return (decimal_value / divisor).quantize(Decimal("0.001")) if scale or decimal_value != decimal_value.to_integral() else decimal_value.quantize(Decimal("0.001"))



def _timestamp_seconds_to_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        ts = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.utcfromtimestamp(ts).replace(microsecond=0)



def _normalize_icon(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return f"https://images.tuyaeu.com/{text.lstrip('/')}"
