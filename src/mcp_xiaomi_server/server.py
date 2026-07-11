#!/usr/bin/env python3
"""MCP Xiaomi Server - Local Mijia (米家) WiFi device tools for LLM agents.

Reads and controls Mijia WiFi devices directly on the LAN via python-miio.
No cloud calls at runtime; device IP/token/model come from a local config file.

Usage:
    mcp-xiaomi-server                      # stdio transport (default)
    MCP_TRANSPORT=sse mcp-xiaomi-server    # HTTP/SSE transport
    MCP_XIAOMI_DEVICES=/path/devices.json mcp-xiaomi-server
"""

import asyncio
import json
import os
import sys
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

from .mihome.base import DeviceError
from .mihome.registry import DeviceRegistry

load_dotenv()

DEVICES_PATH = os.getenv("MCP_XIAOMI_DEVICES", os.path.expanduser("~/.config/mcp-xiaomi-server/devices.json"))
TIMEOUT = int(os.getenv("MCP_XIAOMI_TIMEOUT", "5"))

server = Server("mcp-xiaomi-server")
registry = DeviceRegistry(DEVICES_PATH, timeout=TIMEOUT)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="xiaomi_list_devices",
            description="列出已配置的所有米家设备及其在线状态。返回每个设备的 id、名称、型号、IP、协议和可查询的属性名。先用它了解有哪些设备和属性可用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "check_online": {
                        "type": "boolean",
                        "description": "是否逐一探测设备在线状态（会稍慢）。默认 true。",
                        "default": True,
                    }
                },
            },
        ),
        Tool(
            name="xiaomi_get_status",
            description="读取某个设备的全部实时属性（如开关、温度、湿度、功率等）。这是获取'家里设备实时情况'的主力工具。",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备 id（来自 xiaomi_list_devices）"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="xiaomi_get_property",
            description="读取某个设备的单个属性的实时值。",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备 id"},
                    "property": {"type": "string", "description": "属性名（来自设备配置，如 'temperature'、'switch_on'）"},
                },
                "required": ["device_id", "property"],
            },
        ),
        Tool(
            name="xiaomi_set_property",
            description="设置（控制）某个设备的可写属性，例如开关插座、调节加湿器目标湿度。仅 MIoT 设备且属性 access 含 'w' 时可用。",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备 id"},
                    "property": {"type": "string", "description": "要设置的可写属性名"},
                    "value": {
                        "type": ["boolean", "integer", "number", "string"],
                        "description": "目标值，类型需与属性匹配（开关类用 true/false）",
                    },
                },
                "required": ["device_id", "property", "value"],
            },
        ),
        Tool(
            name="xiaomi_device_info",
            description="获取设备硬件信息与在线状态（型号、固件、硬件版本、MAC）。通过一次握手判断设备是否可达。",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备 id"},
                },
                "required": ["device_id"],
            },
        ),
        Tool(
            name="xiaomi_raw_command",
            description="高级：向设备发送原始 miIO 命令（如 legacy 设备的 get_prop / set_power）。用于配置中未映射的能力。",
            inputSchema={
                "type": "object",
                "properties": {
                    "device_id": {"type": "string", "description": "设备 id"},
                    "command": {"type": "string", "description": "miIO 命令名，如 'get_prop'"},
                    "params": {
                        "type": "array",
                        "description": "命令参数数组，如 ['power','mode']",
                        "items": {},
                        "default": [],
                    },
                },
                "required": ["device_id", "command"],
            },
        ),
        Tool(
            name="xiaomi_get_server_status",
            description="查询服务器状态：设备配置文件路径、加载到的设备数量、以及配置加载是否有错误。",
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        result = await _handle_tool(name, arguments)
        return [TextContent(type="text", text=result)]
    except DeviceError as e:
        return [TextContent(type="text", text=json.dumps(
            {"error": str(e), "device_id": e.device_id}, ensure_ascii=False
        ))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]


async def _handle_tool(name: str, args: dict[str, Any]) -> str:
    if name == "xiaomi_list_devices":
        return await _list_devices(args)
    elif name == "xiaomi_get_status":
        return await _get_status(args)
    elif name == "xiaomi_get_property":
        return await _get_property(args)
    elif name == "xiaomi_set_property":
        return await _set_property(args)
    elif name == "xiaomi_device_info":
        return await _device_info(args)
    elif name == "xiaomi_raw_command":
        return await _raw_command(args)
    elif name == "xiaomi_get_server_status":
        return _server_status()
    else:
        return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)


async def _list_devices(args: dict) -> str:
    check_online = bool(args.get("check_online", True))
    devices = registry.all()

    online_map: dict[str, bool] = {}
    if check_online and devices:
        infos = await asyncio.gather(*(d.get_info() for d in devices), return_exceptions=True)
        for d, info in zip(devices, infos):
            online_map[d.config.id] = getattr(info, "online", False) if not isinstance(info, Exception) else False

    out = []
    for d in devices:
        c = d.config
        entry = {
            "device_id": c.id,
            "name": c.name,
            "model": c.model,
            "ip": c.ip,
            "protocol": c.protocol,
            "properties": c.property_names(),
        }
        if check_online:
            entry["online"] = online_map.get(c.id, False)
        out.append(entry)

    return json.dumps({"count": len(out), "devices": out}, ensure_ascii=False)


async def _get_status(args: dict) -> str:
    device = registry.get(args["device_id"])
    status = await device.read_status()
    return json.dumps(status.to_dict(), ensure_ascii=False)


async def _get_property(args: dict) -> str:
    device = registry.get(args["device_id"])
    name = args["property"]
    value = await device.read_property(name)
    return json.dumps({"device_id": args["device_id"], "property": name, "value": value}, ensure_ascii=False)


async def _set_property(args: dict) -> str:
    device = registry.get(args["device_id"])
    result = await device.set_property(args["property"], args["value"])
    return json.dumps({"status": "ok", **result}, ensure_ascii=False)


async def _device_info(args: dict) -> str:
    device = registry.get(args["device_id"])
    info = await device.get_info()
    return json.dumps(info.to_dict(), ensure_ascii=False)


async def _raw_command(args: dict) -> str:
    device = registry.get(args["device_id"])
    result = await device.raw_command(args["command"], args.get("params", []))
    return json.dumps({"device_id": args["device_id"], "command": args["command"], "result": result}, ensure_ascii=False, default=str)


def _server_status() -> str:
    return json.dumps(
        {
            "devices_config": DEVICES_PATH,
            "device_count": len(registry),
            "timeout": TIMEOUT,
            "load_error": registry.load_error,
        },
        ensure_ascii=False,
    )


async def main():
    """Run the MCP Xiaomi Server. Supports stdio and SSE transports."""
    registry.load()
    if registry.load_error:
        print(f"[mcp-xiaomi-server] {registry.load_error}", file=sys.stderr)
    print(f"[mcp-xiaomi-server] Loaded {len(registry)} device(s) from {DEVICES_PATH}", file=sys.stderr)

    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        await _run_sse()
    else:
        await _run_stdio()


async def _run_stdio():
    """Run server via stdio transport (for local MCP clients)."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def _run_sse():
    """Run server via SSE/HTTP transport (for remote MCP clients)."""
    try:
        from starlette.applications import Starlette
        from starlette.responses import Response
        from starlette.routing import Mount, Route as StarletteRoute
        import uvicorn
    except ImportError:
        print(
            "[mcp-xiaomi-server] SSE transport requires starlette and uvicorn. "
            "Install with: pip install mcp-xiaomi-server[sse]",
            file=sys.stderr,
        )
        sys.exit(1)

    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8092"))

    transport_instance = SseServerTransport("/messages/")

    async def handle_sse(request):
        async with transport_instance.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            StarletteRoute("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=transport_instance.handle_post_message),
        ]
    )

    print(f"[mcp-xiaomi-server] SSE server starting on http://{host}:{port}", file=sys.stderr)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server_instance = uvicorn.Server(config)
    await server_instance.serve()


def run():
    """Synchronous entrypoint for the console script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
