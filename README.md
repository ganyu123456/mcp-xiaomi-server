# MCP Xiaomi Server

为 LLM 大模型提供**本地米家设备**读取与控制能力的 MCP (Model Context Protocol) Server。通过 `python-miio` 在**局域网内直连**米家 WiFi 设备(UDP:54321),读取实时状态(开关、温度、湿度、功率等)并进行控制。**运行时完全不走小米云**,设备的 IP/token 只保存在本地配置文件里。

部署后,支持 MCP 的大模型客户端可以直接问:"客厅插座现在开着吗""卧室湿度多少""把加湿器目标湿度调到 60"。

## 功能

- 列出已配置设备及在线状态
- 读取设备全部实时属性 / 单个属性
- 控制设备可写属性(开关、目标值等)
- 获取设备硬件信息(型号、固件、MAC)
- 原始 miIO 命令透传(高级)
- 支持 MIoT 协议(siid/piid)与传统 miIO 协议(get_prop)两类设备
- 两种传输模式:`stdio`(本地)和 `sse`(远程 HTTP)

## 前置条件:获取设备 IP 与 token

本地直连每个设备都需要 **IP + 32 位 token + model**。token 需**一次性**从小米云获取(之后运行时纯本地):

```bash
pip install python-miio
miiocli cloud   # 用小米账号登录,列出所有设备的 IP / token / model
```

将结果填入设备清单文件(见下)。建议在路由器为设备保留固定 IP,避免 DHCP 变化。

## 设备清单配置

复制示例并填入你的真实设备(参考 `devices.example.json`):

```bash
cp devices.example.json devices.json
```

格式为设备数组,每个设备:

```json
[
  {
    "id": "living_room_plug",
    "name": "客厅插座",
    "ip": "192.168.31.100",
    "token": "0123456789abcdef0123456789abcdef",
    "model": "cuco.plug.v3",
    "protocol": "miot",
    "properties": {
      "switch_on":   { "siid": 2, "piid": 1, "access": "rw", "desc": "开关" },
      "temperature": { "siid": 2, "piid": 6, "access": "r",  "desc": "设备温度(°C)" }
    }
  }
]
```

- `protocol`: `miot`(新设备,用 siid/piid)或 `legacy`(老设备,`properties` 为属性名数组)
- MIoT 设备的 `siid`/`piid` 可在 [spec.miot-spec.com](https://home.miot-spec.com/) 按型号查到
- `access` 含 `w` 的属性才允许 `xiaomi_set_property` 控制

> ⚠️ `devices.json` 含 token,已在 `.gitignore` 中排除,切勿提交到仓库。

## 快速开始

### 本地开发运行

```bash
pip install -e ".[sse]"

cp .env.example .env         # 按需修改
cp devices.example.json devices.json && vim devices.json
export MCP_XIAOMI_DEVICES=$PWD/devices.json

# stdio 模式(本地 MCP 客户端)
MCP_TRANSPORT=stdio python -m mcp_xiaomi_server.server

# SSE 模式(远程 MCP 客户端)
MCP_TRANSPORT=sse python -m mcp_xiaomi_server.server
```

### Docker 部署

> 本地控制需容器与设备**同一局域网**,compose 使用 `network_mode: host`(仅 Linux 宿主机)。

```bash
cp devices.example.json devices.json && vim devices.json
docker compose up -d
```

### CI/CD 自动构建发布

在仓库 **Settings → Secrets and variables → Actions** 添加:

| Secret | 说明 |
|--------|------|
| `HARBOR_USERNAME` | Harbor 用户名 |
| `HARBOR_PASSWORD` | Harbor 密码或访问令牌 |

> 镜像仓库地址已固定为 `harbor.zkjgy.online/library`(写死在 workflow 中)。

打 tag 触发构建:

```bash
git tag v1.0.0
git push origin v1.0.0
```

自动构建 amd64(x86 runner)+ arm64(原生 ARM runner)多架构镜像,推送 Harbor 并创建 GitHub Release。

## MCP 客户端配置

### SSE(远程)

```json
{
  "mcpServers": {
    "xiaomi": {
      "url": "http://<your-server-ip>:8092/sse"
    }
  }
}
```

### stdio(本地)

```json
{
  "mcpServers": {
    "xiaomi": {
      "command": "python",
      "args": ["-m", "mcp_xiaomi_server.server"],
      "env": {
        "MCP_TRANSPORT": "stdio",
        "MCP_XIAOMI_DEVICES": "/path/to/devices.json"
      }
    }
  }
}
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_IMAGE` | `harbor.zkjgy.online/library/mcp-xiaomi-server:latest` | Docker 镜像地址 |
| `MCP_TRANSPORT` | `sse` | 传输模式:`stdio` 或 `sse` |
| `MCP_HOST` | `0.0.0.0` | SSE 模式监听地址 |
| `MCP_PORT` | `8092` | SSE 模式监听端口 |
| `MCP_XIAOMI_DEVICES` | `~/.config/mcp-xiaomi-server/devices.json` | 设备清单文件路径 |
| `MCP_XIAOMI_TIMEOUT` | `5` | 单次设备通信超时(秒) |

## MCP 工具列表

| 工具 | 说明 |
|------|------|
| `xiaomi_list_devices` | 列出设备及在线状态 |
| `xiaomi_get_status` | 读取某设备全部实时属性(主力工具) |
| `xiaomi_get_property` | 读取单个属性实时值 |
| `xiaomi_set_property` | 控制可写属性(开关、目标值等) |
| `xiaomi_device_info` | 设备硬件信息与在线判断 |
| `xiaomi_raw_command` | 原始 miIO 命令透传(高级) |
| `xiaomi_get_server_status` | 服务器与配置状态 |

### 工具调用示例

```
列出设备:  xiaomi_list_devices()
读实时状态:xiaomi_get_status(device_id="living_room_plug")
读单个属性:xiaomi_get_property(device_id="bedroom_humidifier", property="humidity")
控制设备:  xiaomi_set_property(device_id="living_room_plug", property="switch_on", value=true)
```

## 项目结构

```
mcp-xiaomi-server/
├── src/mcp_xiaomi_server/
│   ├── server.py                # MCP 服务器入口,工具定义与分发
│   └── mihome/
│       ├── base.py              # 设备配置与数据模型
│       ├── local.py             # python-miio 本地读写封装
│       └── registry.py          # 设备清单加载与管理
├── devices.example.json         # 设备清单示例
├── Dockerfile
├── docker-compose.yaml
├── .github/workflows/
│   └── build-release.yaml       # CI/CD 工作流
├── requirements.txt
├── pyproject.toml
└── .env.example
```

## 局限与说明

- 仅覆盖 **WiFi 直连设备**。Zigbee/BLE 子设备(挂在小米网关下)需另走网关方案(telnet + MQTT),不在本项目范围。
- MCP 服务器必须与设备处于**同一局域网**。
- token 变更(如设备重置/重新配网)后需更新 `devices.json`。

## License

MIT
