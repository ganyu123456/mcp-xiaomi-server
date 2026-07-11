"""Local Mijia device client built on python-miio.

Communicates with WiFi Mijia devices directly on the LAN (UDP:54321). All
python-miio calls are blocking, so they are dispatched to a thread and bounded
by a timeout to keep the async MCP server responsive.
"""

import asyncio
from typing import Any

from .base import DeviceConfig, DeviceError, DeviceInfo, DeviceStatus, PropertySpec


class LocalDevice:
    """Wraps one configured device for local read/write over the LAN."""

    def __init__(self, config: DeviceConfig, timeout: int = 5):
        self.config = config
        self._timeout = max(1, int(timeout))
        self._device = None

    # -- device construction -------------------------------------------------

    def _ensure_device(self):
        if self._device is not None:
            return self._device
        try:
            from miio import Device, MiotDevice
        except ImportError as e:  # pragma: no cover
            raise DeviceError(self.config.id, f"python-miio is not installed: {e}")

        cls = MiotDevice if self.config.protocol == "miot" else Device
        base = {"ip": self.config.ip, "token": self.config.token}
        model_kw = {"model": self.config.model} if self.config.model else {}

        # Try the richest constructor first, then drop kwargs that older
        # python-miio versions don't accept (model/timeout were added in 0.6.0).
        for extra in (
            {"lazy_discover": True, "timeout": self._timeout, **model_kw},
            {"lazy_discover": True, **model_kw},
            {"lazy_discover": True},
        ):
            try:
                self._device = cls(**base, **extra)
                return self._device
            except TypeError:
                continue
        self._device = cls(self.config.ip, self.config.token)
        return self._device

    # -- low-level dispatch --------------------------------------------------

    def _send(self, command: str, params: Any) -> Any:
        return self._ensure_device().send(command, params)

    async def _call(self, command: str, params: Any) -> Any:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._send, command, params),
                timeout=self._timeout + 3,
            )
        except asyncio.TimeoutError:
            raise DeviceError(self.config.id, f"Timeout talking to device at {self.config.ip}.")
        except DeviceError:
            raise
        except Exception as e:
            raise DeviceError(self.config.id, f"{type(e).__name__}: {e}")

    # -- info / online -------------------------------------------------------

    def _raw_info(self):
        return self._ensure_device().info()

    async def get_info(self) -> DeviceInfo:
        info = DeviceInfo(
            device_id=self.config.id,
            name=self.config.name,
            model=self.config.model,
            ip=self.config.ip,
        )
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(self._raw_info), timeout=self._timeout + 3
            )
            info.online = True
            info.model = getattr(raw, "model", "") or self.config.model
            info.firmware = getattr(raw, "firmware_version", "") or ""
            info.hardware = getattr(raw, "hardware_version", "") or ""
            info.mac = getattr(raw, "mac_address", "") or ""
        except Exception:
            info.online = False
        return info

    # -- reads ---------------------------------------------------------------

    async def _read_miot(self, specs: dict[str, PropertySpec]) -> dict[str, Any]:
        query = [{"did": s.name, "siid": s.siid, "piid": s.piid} for s in specs.values()]
        resp = await self._call("get_properties", query)
        out: dict[str, Any] = {}
        if isinstance(resp, list):
            for item in resp:
                if isinstance(item, dict) and "did" in item:
                    out[item["did"]] = item.get("value") if item.get("code") == 0 else None
        return out

    async def _read_legacy(self, names: list[str]) -> dict[str, Any]:
        resp = await self._call("get_prop", names)
        out: dict[str, Any] = {}
        if isinstance(resp, list):
            for name, val in zip(names, resp):
                out[name] = val
        return out

    async def read_status(self) -> DeviceStatus:
        status = DeviceStatus(
            device_id=self.config.id, name=self.config.name, model=self.config.model
        )
        names = self.config.property_names()
        if not names:
            info = await self.get_info()
            status.online = info.online
            return status
        try:
            if self.config.protocol == "miot":
                assert isinstance(self.config.properties, dict)
                status.properties = await self._read_miot(self.config.properties)
            else:
                status.properties = await self._read_legacy(names)
            status.online = True
        except DeviceError as e:
            status.online = False
            status.errors["error"] = e.message
        return status

    async def read_property(self, name: str) -> Any:
        if self.config.protocol == "miot":
            specs = self.config.properties
            spec = specs.get(name) if isinstance(specs, dict) else None
            if spec is None:
                raise DeviceError(
                    self.config.id,
                    f"Unknown property '{name}'. Known: {self.config.property_names()}",
                )
            values = await self._read_miot({name: spec})
            return values.get(name)
        values = await self._read_legacy([name])
        return values.get(name)
