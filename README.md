# MCP Xiaomi Server

为 LLM 大模型提供**本地米家设备**读取能力的 MCP (Model Context Protocol) Server。通过 `python-miio` 在**局域网内直连**米家 WiFi 设备(UDP:54321),读取实时状态(开关、温度、湿度、功率等);并可对**摄像头**抓拍照片、录制短视频。**本 Server 只读,不含任何写入/控制设备的工具**;设备的 IP/token 只保存在本地配置文件里,运行时完全不走小米云。

部署后,支持 MCP 的大模型客户端可以直接问:"客厅插座现在开着吗""卧室湿度多少""工作室摄像头现在拍到了什么"。

## 功能

- 列出已配置设备及在线状态
- 读取设备全部实时属性 / 单个属性
- 获取设备硬件信息(型号、固件、MAC)
- 摄像头抓拍照片(返回 JPEG 图片)、录制 N 秒视频(保存为 MP4)
- 支持 MIoT 协议(siid/piid)与传统 miIO 协议(get_prop)两类设备
- 两种传输模式:`stdio`(本地)和 `sse`(远程 HTTP)

> **只读设计**:本 Server 刻意不提供任何写入/控制工具(不能开关设备、不能改参数、无原始命令透传),避免大模型误操作家里的电器。

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

格式为设备数组。**普通 miIO/MIoT 设备**:

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
      "switch_on":   { "siid": 2, "piid": 1, "desc": "开关" },
      "temperature": { "siid": 2, "piid": 6, "desc": "设备温度(°C)" }
    }
  }
]
```

- `protocol`: `miot`(新设备,用 siid/piid)或 `legacy`(老设备,`properties` 为属性名数组)
- MIoT 设备的 `siid`/`piid` 可在 [spec.miot-spec.com](https://home.miot-spec.com/) 按型号查到

**摄像头**(`protocol: "camera"`)不走 python-miio,而是从一条**本地 RTSP 流**抓帧/录制,只需填 `rtsp_url`:

```json
{
  "id": "study_cam",
  "name": "工作室摄像头",
  "protocol": "camera",
  "rtsp_url": "rtsp://127.0.0.1:8554/camera_1"
}
```

> ⚠️ `devices.json` 含 token,已在 `.gitignore` 中排除,切勿提交到仓库。

### 摄像头的 RTSP 从哪来

米家摄像头不走 UDP:54321,本 Server 只负责用 `ffmpeg` 从一个现成的 RTSP 地址抓帧/录制。你需要另有一个把摄像头发布成本地 RTSP 的网关(例如把小米 P2P 流通过 MediaMTX 重发布为 `rtsp://127.0.0.1:8554/camera_x`),把该地址填进 `rtsp_url` 即可。运行本 Server 的机器需能访问该 RTSP,且已安装 `ffmpeg`。

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

> 摄像头抓拍/录制依赖 `ffmpeg`,请确保已安装(Docker 镜像已内置)。

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
git tag v1.1.0
git push origin v1.1.0
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
| `MCP_XIAOMI_FFMPEG` | `ffmpeg` | ffmpeg 可执行文件路径(摄像头抓拍/录制用) |
| `MCP_XIAOMI_CLIP_DIR` | 系统临时目录 | 摄像头录制 MP4 的保存目录 |

## MCP 工具列表

| 工具 | 说明 |
|------|------|
| `xiaomi_list_devices` | 列出设备(含摄像头)及在线状态 |
| `xiaomi_get_status` | 读取某设备全部实时属性(主力工具) |
| `xiaomi_get_property` | 读取单个属性实时值 |
| `xiaomi_device_info` | 设备硬件信息与在线判断 |
| `xiaomi_camera_snapshot` | 抓取摄像头当前画面,返回 JPEG 图片 |
| `xiaomi_camera_clip` | 录制摄像头一段视频(默认 10 秒),返回 MP4 路径 |
| `xiaomi_get_server_status` | 服务器与配置状态 |

> 本 Server 为**只读**:不提供设置属性、开关设备或原始命令透传等写入工具。

### 工具调用示例

```
列出设备:  xiaomi_list_devices()
读实时状态:xiaomi_get_status(device_id="living_room_plug")
读单个属性:xiaomi_get_property(device_id="bedroom_humidifier", property="humidity")
摄像头抓拍:xiaomi_camera_snapshot(device_id="study_cam")
摄像头录制:xiaomi_camera_clip(device_id="study_cam", seconds=10)
```

## 项目结构

```
mcp-xiaomi-server/
├── src/mcp_xiaomi_server/
│   ├── server.py                # MCP 服务器入口,工具定义与分发
│   ├── camera.py                # 摄像头抓拍/录制(ffmpeg 拉本地 RTSP)
│   └── mihome/
│       ├── base.py              # 设备配置与数据模型
│       ├── local.py             # python-miio 本地只读封装
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

- 本 Server **只读**,不含任何控制/写入设备的工具。
- 普通设备仅覆盖 **WiFi 直连设备**。Zigbee/BLE 子设备(挂在小米网关下)需另走网关方案,不在本项目范围。
- 普通设备的 MCP 服务器必须与设备处于**同一局域网**;token 变更(设备重置/重新配网)后需更新 `devices.json`。
- 摄像头能力依赖一个**外部的 RTSP 网关**(把摄像头发布成本地 RTSP)与 `ffmpeg`;本 Server 本身不直接对接摄像头 SDK/云。

## License

MIT
