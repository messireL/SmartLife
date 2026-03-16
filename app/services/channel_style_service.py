from __future__ import annotations

CHANNEL_ROLE_CHOICES = [
    {"key": "", "label": "Без роли", "default_icon": "auto"},
    {"key": "general", "label": "Обычная нагрузка", "default_icon": "plug"},
    {"key": "pc", "label": "ПК", "default_icon": "pc"},
    {"key": "monitor", "label": "Монитор", "default_icon": "monitor"},
    {"key": "router", "label": "Роутер / сеть", "default_icon": "router"},
    {"key": "charger", "label": "Зарядки", "default_icon": "charger"},
    {"key": "kettle", "label": "Чайник", "default_icon": "kettle"},
    {"key": "boiler", "label": "Бойлер / нагрев", "default_icon": "heater"},
    {"key": "light", "label": "Свет", "default_icon": "light"},
    {"key": "tv", "label": "ТВ / медиазона", "default_icon": "tv"},
    {"key": "audio", "label": "Аудио", "default_icon": "audio"},
    {"key": "appliance", "label": "Техника", "default_icon": "plug"},
    {"key": "other", "label": "Другое", "default_icon": "tag"},
]

CHANNEL_ICON_CHOICES = [
    {"key": "auto", "label": "Авто по роли", "symbol": "◌"},
    {"key": "plug", "label": "Розетка", "symbol": "🔌"},
    {"key": "pc", "label": "ПК", "symbol": "💻"},
    {"key": "monitor", "label": "Монитор", "symbol": "🖥️"},
    {"key": "router", "label": "Сеть", "symbol": "📡"},
    {"key": "charger", "label": "Зарядка", "symbol": "🔋"},
    {"key": "kettle", "label": "Чайник", "symbol": "☕"},
    {"key": "heater", "label": "Нагрев", "symbol": "♨️"},
    {"key": "light", "label": "Свет", "symbol": "💡"},
    {"key": "tv", "label": "ТВ", "symbol": "📺"},
    {"key": "audio", "label": "Аудио", "symbol": "🔊"},
    {"key": "usb", "label": "USB", "symbol": "🔋"},
    {"key": "tag", "label": "Метка", "symbol": "🏷️"},
]

_ROLE_MAP = {item["key"]: item for item in CHANNEL_ROLE_CHOICES}
_ICON_MAP = {item["key"]: item for item in CHANNEL_ICON_CHOICES}


def get_channel_role_choices() -> list[dict[str, str]]:
    return list(CHANNEL_ROLE_CHOICES)


def get_channel_icon_choices() -> list[dict[str, str]]:
    return list(CHANNEL_ICON_CHOICES)


def get_channel_role_label(key: str | None) -> str | None:
    cleaned = (key or "").strip()
    if not cleaned:
        return None
    item = _ROLE_MAP.get(cleaned)
    return item["label"] if item else cleaned


def normalize_channel_role_key(key: str | None) -> str | None:
    cleaned = (key or "").strip()
    if not cleaned:
        return None
    return cleaned if cleaned in _ROLE_MAP and cleaned else None


def normalize_channel_icon_key(key: str | None) -> str:
    cleaned = (key or "auto").strip() or "auto"
    return cleaned if cleaned in _ICON_MAP else "auto"


def resolve_channel_icon(group: str | None, role_key: str | None, explicit_icon_key: str | None) -> tuple[str, str, bool]:
    icon_key = normalize_channel_icon_key(explicit_icon_key)
    if icon_key != "auto":
        item = _ICON_MAP[icon_key]
        return item["key"], item["symbol"], False
    normalized_role = normalize_channel_role_key(role_key)
    if normalized_role:
        default_icon = _ROLE_MAP[normalized_role].get("default_icon") or "plug"
        item = _ICON_MAP.get(default_icon, _ICON_MAP["plug"])
        return item["key"], item["symbol"], True
    if (group or "") == "usb":
        item = _ICON_MAP["usb"]
        return item["key"], item["symbol"], True
    item = _ICON_MAP["plug"]
    return item["key"], item["symbol"], True
