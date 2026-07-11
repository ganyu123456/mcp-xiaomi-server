"""Loads the device config file and holds a LocalDevice per configured device."""

import json
import os
from pathlib import Path
from typing import Optional

from .base import DeviceConfig, DeviceError
from .local import LocalDevice


class DeviceRegistry:
    """Registry of configured Mijia devices, keyed by device id."""

    def __init__(self, config_path: str, timeout: int = 5):
        self.config_path = config_path
        self.timeout = timeout
        self._devices: dict[str, LocalDevice] = {}
        self._load_error: Optional[str] = None

    def load(self) -> None:
        """Load (or reload) devices from the config file. Never raises."""
        self._devices = {}
        self._load_error = None

        path = Path(os.path.expanduser(self.config_path))
        if not path.exists():
            self._load_error = f"Device config not found: {path}"
            return

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            self._load_error = f"Failed to read device config: {e}"
            return

        entries = raw.get("devices", raw) if isinstance(raw, dict) else raw
        if not isinstance(entries, list):
            self._load_error = "Device config must be a JSON array of devices (or {\"devices\": [...]})."
            return

        for entry in entries:
            try:
                config = DeviceConfig.from_dict(entry)
            except DeviceError as e:
                # Skip a bad entry but keep loading the rest.
                continue
            if config.id in self._devices:
                continue
            self._devices[config.id] = LocalDevice(config, timeout=self.timeout)

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def get(self, device_id: str) -> LocalDevice:
        device = self._devices.get(device_id)
        if device is None:
            known = ", ".join(self._devices.keys()) or "(none)"
            raise DeviceError(device_id, f"Device not found. Configured: {known}")
        return device

    def all(self) -> list[LocalDevice]:
        return list(self._devices.values())

    def configs(self) -> list[DeviceConfig]:
        return [d.config for d in self._devices.values()]

    def __len__(self) -> int:
        return len(self._devices)
