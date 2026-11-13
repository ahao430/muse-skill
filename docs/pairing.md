# Muse 配对与授权（一次性）

本文档独立说明如何完成 Muse 的 BLE 配对。**配对只需做一次**。
推荐路径是 **Mac 本机配对**（方式一，无需任何额外硬件）。

## 0. 前置条件

- Muse 账号 + 手机上装好 Muse app
- **SDK Token**：[gadgets.muse.ai](https://gadgets.muse.ai/settings/sdk-tokens)
  → Account → SDK tokens 生成（`mgst_…`）。先阅读 Gadget SDK Terms。
  ⚠️ Token 等同凭证：不要提交进 git、不要贴到聊天/issue。
- **网络**：配对时手机必须能访问 `hatch-api.meta.ai`（Meta 域名，国内
  网络可能需要手机和电脑都挂代理）。

## 方式一（推荐）：Mac 本机蓝牙配对

使用社区 [muse-client](https://github.com/wong2/muse-client)（Apache-2.0，
官方 Gadget SDK 协议的 TypeScript 实现，支持 macOS CoreBluetooth 配对）。
本仓库已内置其包装脚本。

```sh
# 1. Xcode Command Line Tools（装过可跳过）
xcode-select --install

# 2. 安装依赖（仓库 bridge/ 目录）
cd bridge && bun install && cd ..

# 3. 配对（会提示粘贴 SDK Token、请求蓝牙权限）
export MUSE_SDK_TOKEN=mgst_…        # 或运行时按提示粘贴
bun bridge/bridge.mjs pair
```

手机端：

1. Muse app → Settings → Devices → 打开 **Developer mode**
2. Add Device（+）→ 选择终端显示的 `MuseGadgetXXXXXX`
3. 提示 community device → 继续（自己的设备）
4. Wi-Fi 选 **Use current connection**

看到 `Paired successfully` 即完成。凭证保存在
`~/Library/Application Support/MuseGadgetPair/`，token 之后自动刷新。
验证：`bun bridge/bridge.mjs status` 应返回 `"paired": true, "ready": true`。

> 排错：配对卡在 Wi-Fi 之后 → 多半是手机访问 `hatch-api.meta.ai` 不通，
> 检查手机代理。换 SDK token 后需先 unpair 再重新 pair（见 muse-client CLI）。

## 方式二（可选后端）：Linux gadget 主机

若需要 24/7 常驻（Mac 关机也能收发），改用云主机跑官方 musegadget：

```sh
scripts/provision.sh --host USER@HOST --sdk-token mgst_…   # 部署 SDK + 服务
```

它没有蓝牙，配对仍需在一台有 BLE 的 Linux 完成（WSL2 + usbipd 直通 USB
蓝牙适配器，或树莓派）：

```sh
# WSL2 (Ubuntu 22.04+)，Windows 侧先 usbipd attach 蓝牙适配器
sudo apt install -y bluez python3-dbus python3-gi
curl -fsSL -o install.sh \
  https://raw.githubusercontent.com/facebookincubator/muse-gadget-sdk/main/linux/install.sh
sudo bash install.sh --sdk-token mgst_… --yes
sudo musegadget pair              # 手机 app 同上配对
# 导出并导入云主机
sudo cp /var/lib/musegadget/{identity,pairing}.json ~/
scp identity.json pairing.json you@mac:~/muse-pairing/
MUSE_AGENT_HOST=USER@HOST scripts/import_state.sh ~/muse-pairing
```

然后在 `~/.config/muse-agent/config.yaml` 里切换后端：

```yaml
backend: ssh        # local（默认，Mac 直连）| ssh（云主机常驻）
host: USER@HOST     # backend: ssh 时使用
```

## 凭证可迁移：Windows 上使用

**配对凭证与机器无关、可自由拷贝**；聊天运行时（muse-client）是纯 TS，
Windows 也能跑。所以：**借任意一台有蓝牙的机器授权一次，之后目标机独立
运行，配对机即退役**。

- 配对机为 Mac：拷 `~/Library/Application Support/MuseGadgetPair/` 整个目录
- 配对机为 WSL2/Linux：拷 `/var/lib/musegadget/` 下的 `identity.json` + `pairing.json`

目标机（Windows/Linux/Mac 皆可）：

1. 安装本仓库（uv + bun，`cd bridge && bun install`）
2. 凭证放到任意目录，`~/.config/muse-agent/config.yaml` 里指向它：
   ```yaml
   backend: local
   credentials_dir: /path/to/MuseGadgetPair
   ```
3. `bun bridge/bridge.mjs status` 验证 `"ready": true`

注意：**配对动作本身不支持在 Windows 上执行**（`pairMacOS` 依赖
CoreBluetooth，官方 SDK 依赖 BlueZ）——Windows 只作为"已授权后"的运行平台。
路线 B（ssh 后端）下 Windows 也可以直接当 MCP 客户端，gadget 主机用 WSL2
或云主机承担。

## 安全须知

- SDK Token、配对凭证目录 **永不入库**（.gitignore 已排除）；拷贝凭证时
  同样注意别经过不可信渠道。
- SSH 后端下，musegadget 会把 `system.run` / `file.*` 能力交给 Muse
  （以安装账号权限运行）；**断开连接不会取消已开始的命令**（官方已知行为）。
  不需要可自行裁剪命令（`/etc/musegadget/commands.d/`）。
- local 后端（muse-client）不注册任何本地命令，Muse 只能与你聊天/收发图片。
- 配对是 community 模式，无厂商验证，请在可信网络完成。
