from __future__ import annotations

import re
import subprocess
from pathlib import Path

_MAC_RE = re.compile(r"([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")


def resolve_local_mac(ip_address: str | None) -> str:
    ip_text = str(ip_address or "").strip()
    if not ip_text:
        return ""

    for command in (("ip", "neigh", "show", ip_text), ("ip", "neigh", "get", ip_text)):
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=3, check=False)
        except Exception:  # noqa: BLE001
            continue
        value = _extract_mac(result.stdout) or _extract_mac(result.stderr)
        if value:
            return value

    arp_file = Path("/proc/net/arp")
    if arp_file.exists():
        try:
            for line in arp_file.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
                parts = line.split()
                if len(parts) >= 4 and parts[0] == ip_text:
                    value = _extract_mac(parts[3])
                    if value:
                        return value
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _extract_mac(raw: str | None) -> str:
    match = _MAC_RE.search(str(raw or ""))
    return match.group(1).upper() if match else ""
