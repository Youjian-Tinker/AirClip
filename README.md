# AirClip

AirClip 是一个基于 Bluetooth Low Energy（BLE）的剪贴板桥接工具，用于两台可信 Windows 电脑之间没有普通网络通路、但需要同步文本剪贴板的场景。项目使用 ESP32 作为轻量 BLE 中继，每台电脑运行一个 Python 桌面端代理。

典型拓扑：

```text
Windows 电脑 A <-> BLE <-> ESP32 中继 <-> BLE <-> Windows 电脑 B
```

ESP32 固件只负责 BLE 广播、接收和转发。剪贴板历史、去重、启停控制、回环防护等逻辑都放在 Windows 桌面端代理中。

## 功能特性

- 基于 Arduino 和 `NimBLE-Arduino` 的 ESP32 中继固件。
- 面向 Windows 的 Python 桌面端代理，支持控制台和托盘菜单。
- 双向同步文本剪贴板，保留换行、缩进、制表符和 Unicode 字符。
- 本地剪贴板历史默认最多保留 50 条。
- 支持运行时从托盘菜单或控制台启用、暂停、清空历史和退出。
- 使用分块 BLE 协议，剪贴板文本可以超过单个 BLE 包长度。

当前版本只同步纯文本。图片、文件、Word/浏览器富文本样式等暂不支持，因为这些内容体积大、隐私风险高，并且不适合低带宽蓝牙链路。

## 项目结构

```text
desktop-agent/                 Python 桌面端剪贴板代理
desktop-agent/airclip_agent/   桌面端源码
desktop-agent/tests/           桌面端测试
firmware/airclip_esp32/        ESP32 中继 Arduino 固件
docs/architecture.md           组件架构说明
docs/protocol.md               BLE 服务和消息协议
docs/windows-esp32-s3-runbook.md
```

## 环境要求

- Windows 10 或更高版本。
- Python 3.11 或更高版本。
- 支持 BLE 的 ESP32 开发板，主要测试目标是 ESP32-S3-N16R8。
- Arduino ESP32 board package。
- `NimBLE-Arduino` 库。

## 快速开始

### 1. 烧录 ESP32 中继

1. 安装 Arduino ESP32 board package。
2. 安装 `NimBLE-Arduino` 库。
3. 在 Arduino IDE 中打开 `firmware/airclip_esp32/airclip_esp32.ino`。
4. 选择匹配 ESP32-S3-N16R8 的 ESP32-S3 开发板配置并上传。

设备会以 `AirClip-Relay` 名称进行 BLE 广播。

### 2. 安装桌面端代理

新 Windows 电脑上推荐使用安装脚本：

```powershell
cd desktop-agent
.\install.cmd
```

安装脚本会创建本地虚拟环境、安装依赖、添加启动 `AirClipAgent.exe` 的快捷方式，并可选择启用开机自启。安装完成后会启动一次代理。

如果只想手动运行：

```powershell
cd desktop-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m airclip_agent --name pc-a
```

运行时控制台命令：

- `on`：启用共享。
- `off`：暂停共享。
- `history`：打印最近的文本剪贴板历史。
- `clear`：清空本地历史。
- `quit`：退出代理。

托盘图标提供同样的启用、暂停、清空历史和退出控制。控制台环境可以使用 `--no-tray` 禁用托盘；快捷方式或开机自启场景可以使用 `--no-console` 隐藏控制台。托盘菜单中的 `查看历史` 会打开最近剪贴板队列窗口。

## 开发

安装开发依赖并运行测试：

```powershell
cd desktop-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]
pytest
```

Python 包元数据位于 `desktop-agent/pyproject.toml`。`requirements.txt` 保留给 Windows 安装脚本和简单手动安装流程使用。

## 文档

- [架构说明](docs/architecture.md)
- [BLE 协议](docs/protocol.md)
- [Windows 与 ESP32-S3 运行手册](docs/windows-esp32-s3-runbook.md)

## 卸载

```powershell
cd desktop-agent
.\uninstall.cmd
```

## 安全说明

- 两台电脑的名称应保持唯一，代理会用名称防止剪贴板回环。
- 剪贴板内容可能包含敏感信息。不要同步密码、令牌、私钥、生产凭据或来自不可信机器的数据。
- 当前实现会保留本地剪贴板历史队列，但不会把历史作为跨设备共享状态。
- ESP32-S3-N16R8 的内存足够支撑当前中继设计。如果宿主 BLE 栈无法稳定维持两个同时连接，固件仍可复用，但连接策略需要改为轮询或重连模型。

## 许可证

AirClip 使用 [MIT License](LICENSE) 发布。
