# Muse Gadget 配对与授权（一次性）

本文档独立说明如何完成 Muse 官方 SDK 的 BLE 配对，并把配对产物导入常驻的
gadget 主机（云主机）。**配对只需做一次**，之后配对机器可以关机丢弃。

## 0. 前置条件

- Muse 账号 + 手机上装好 Muse app
- **SDK Token**：到 [gadgets.muse.ai](https://gadgets.muse.ai/settings/sdk-tokens)
  → Account → SDK tokens 生成（`mgst_…`）。阅读 Gadget SDK Terms。
  ⚠️ Token 等同凭证：不要提交进 git、不要贴到聊天/issue。
- 一台**有 BLE 的标准 Linux**（配对机）。云主机没有蓝牙，不能作配对机。

## 1. 配对机准备（Windows 台式机 + WSL2 路线）

需要一个 **USB 蓝牙适配器**（Bluetooth 4.0+，几十元即可）。WSL2 用不了
Windows 的内置蓝牙，必须 USB 直通。

```powershell
# Windows 管理员 PowerShell
winget install usbipd
usbipd list                       # 找到蓝牙适配器的 BUSID，如 2-3
usbipd bind --busid <BUSID>
usbipd attach --wsl --busid <BUSID>
```

WSL2（建议 Ubuntu 22.04+）内：

```sh
# 确认适配器已被 WSL 接管
lsusb | grep -i blue
sudo apt update && sudo apt install -y bluez python3-dbus python3-gi

# 安装官方 SDK 并开始配对（打开 BLE 广播 10 分钟）
curl -fsSL -o install.sh \
  https://raw.githubusercontent.com/facebookincubator/muse-gadget-sdk/main/linux/install.sh
less install.sh                   # 先读一遍
sudo bash install.sh --sdk-token mgst_… --yes --no-pair   # 先装
sudo musegadget pair              # 再开配对窗口
```

### 2. 手机端配对

1. Muse app → Settings → Devices → 打开 **Developer mode**
2. Add Device（+）→ 选择 `MuseGadgetXXXXXX`（终端打印的名字）
3. 提示 community device → 继续（是自己的设备）
4. Wi-Fi 步骤选当前网络即可（WSL 已联网，不需要密码）
5. 成功后 `musegadget info` 应显示 paired

> 排错：GATT 133 → 手机开关蓝牙重试；WSL 看不到适配器 → 重新
> `usbipd detach` / `attach`。

## 3. 导出配对产物

配对机上：

```sh
# WSL 里
sudo cp /var/lib/musegadget/identity.json /var/lib/musegadget/pairing.json ~/
sudo chown $USER ~/identity.json ~/pairing.json
# 拷回 Mac（示例）
scp identity.json pairing.json you@mac:~/muse-pairing/
```

## 4. 导入 gadget 主机（云主机）

Mac 上：

```sh
MUSE_AGENT_HOST='root@2607:9d00:2000:143::31b0:2854' \
  scripts/import_state.sh ~/muse-pairing
```

脚本会：拷贝两个 JSON 到云主机 `/var/lib/musegadget/`（0600）→ 重启
musegadget 服务 → 打印 `info`。看到服务 active 且 paired 即成功。
此后配对机（WSL）不再需要。

## 5. 云主机首次部署（若尚未装 SDK）

```sh
scripts/provision.sh --host 'root@2607:9d00:2000:143::31b0:2854' --sdk-token mgst_…
scripts/provision.sh --dry-run   # 先看会执行什么
```

## 安全须知

- SDK Token、`identity.json`、`pairing.json` 都是凭证，**永不入库**（.gitignore 已排除）。
- musegadget 会把 `system.run` / `file.read` / `file.write` 能力交给 Muse，
  以安装时指定的账号权限运行。云主机上若不需要，可只导入 state 用于
  收发消息，并自行裁剪命令（`/etc/musegadget/commands.d/`，见官方文档）。
- 官方已知行为：**断开连接不会取消已开始的命令**，已开始的命令会继续跑完。
- 配对是 community 模式，无厂商验证，请在可信网络完成。
