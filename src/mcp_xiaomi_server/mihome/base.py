"""Data models and errors for Mijia (米家) local devices.

Devices are configured in a JSON file (see devices.example.json). Each device
declares its LAN ``ip``, 32-hex ``token``, ``model`` and a ``protocol``:

- ``miot``   : modern MIoT devices, read/written via (siid, piid) property maps
- ``legacy`` : older miIO devices, read via a flat list of property names

All device communication is local over the LAN (UDP:54321); no cloud calls are
made at runtime. Tokens are obtained once (e.g. via ``miiocli cloud``) and kept
only in the local config file.
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Union


class DeviceError(Exception):
    """Raised when a device operation fails."""

    def __init__(self, device_id: str, message: str):
        self.device_id = device_id
        self.message = message
        super().__init__(f"[{device_id}] {message}")


@dataclass
class PropertySpec:
    """A single MIoT property mapping (siid/piid) for a device."""

    name: str
    siid: int
    piid: int
    access: str = "r"  # "r" (read-only) or "rw" (readable + writable)
    desc: str = ""

    @property
    def writable(self) -> bool:
        return "w" in self.access.lower()


@dataclass
class DeviceConfig:
    """One device entry loaded from the config file."""

    id: str
    name: str
    ip: str
    token: str
    model: str = ""
    protocol: str = "miot"  # "miot" or "legacy"
    # miot: dict[name -> PropertySpec]; legacy: list[str] of prop names
    properties: Union[dict[str, PropertySpec], list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> "DeviceConfig":
        for required in ("id", "ip", "token"):
            if not raw.get(required):
                raise DeviceError(raw.get("id", "?"), f"Config missing required field '{required}'.")

        protocol = (raw.get("protocol") or "miot").strip().lower()
        raw_props = raw.get("properties", {})

        if protocol == "miot":
            props: dict[str, PropertySpec] = {}
            if isinstance(raw_props, dict):
                for name, spec in raw_props.items():
                    if not isinstance(spec, dict) or "siid" not in spec or "piid" not in spec:
                        raise DeviceError(raw["id"], f"Property '{name}' must define siid and piid.")
                    props[name] = PropertySpec(
                        name=name,
                        siid=int(spec["siid"]),
                        piid=int(spec["piid"]),
                        access=str(spec.get("access", "r")),
                        desc=str(spec.get("desc", "")),
                    )
            properties: Union[dict, list] = props
        else:
            properties = list(raw_props) if isinstance(raw_props, list) else []

        return cls(
            id=str(raw["id"]),
            name=str(raw.get("name", raw["id"])),
            ip=str(raw["ip"]),
            token=str(raw["token"]),
            model=str(raw.get("model", "")),
            protocol=protocol,
            properties=properties,
        )

    def property_names(self) -> list[str]:
        if isinstance(self.properties, dict):
            return list(self.properties.keys())
        return list(self.properties)


@dataclass
class DeviceInfo:
    """Hardware info reported by a device handshake."""

    device_id: str
    name: str
    model: str = ""
    ip: str = ""
    online: bool = False
    firmware: str = ""
    hardware: str = ""
    mac: str = ""

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "model": self.model,
            "ip": self.ip,
            "online": self.online,
            "firmware": self.firmware,
            "hardware": self.hardware,
            "mac": self.mac,
        }


@dataclass
class DeviceStatus:
    """A snapshot of a device's current property values."""

    device_id: str
    name: str
    model: str = ""
    online: bool = False
    properties: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        result = {
            "device_id": self.device_id,
            "name": self.name,
            "model": self.model,
            "online": self.online,
            "properties": self.properties,
        }
        if self.errors:
            result["errors"] = self.errors
        return result
