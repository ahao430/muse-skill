# Muse Agent Skill

把 [Muse](https://muse.ai) 接入 coding agents（Claude Code / Zcode 等）：
通过 **MCP** + **Agent Skills**，让 agent 能向 Muse 发消息、收回答、发图片，
做跨 agent 协作。全链路本地，无公网服务器。**已端到端验证**：文字/新会话/
图片收发、异步画图（原生 MCP ImageContent 内联）、COS 中转（画图→Muse
curl 上传→直链，零审批弹窗）。

## 一、方案路线（两条，二选一或都配）

两条路线底层都是官方 **Gadget 协议**（WSS + Noise 加密会话直连 Muse VM），
区别只是"设备角色"跑在哪台机器上。**蓝牙只在配对那一刻用一次**，之后
手机彻底退出链路。

```
路线 A（手机配对直连 · 社区 muse-client）
  Claude Code / Zcode ──MCP stdio──> muse-agent（本仓库，Mac）
                                        │ backend: local（默认）
                                        ▼
                     muse-client（TS 移植，Mac 内置蓝牙配对一次）
                                        │ WSS + Noise（走互联网）
                                        ▼
                                     Muse VM

路线 B（Linux SDK 常驻 · 官方 musegadget）
  Claude Code / Zcode ──MCP stdio──> muse-agent（Mac）
                                        │ backend: ssh
                                        ▼
                     musegadget systemd 服务（云主机/树莓派，24/7）
                                        │ WSS + Noise
                                        ▼
                                     Muse VM
```

| | 路线 A：手机配对（local） | 路线 B：Linux SDK（ssh） |
|---|---|---|
| 配对 | **Mac 本机**，内置蓝牙，零硬件 | 在任意有 BLE 的 Linux 配对一次（**需要 USB 蓝牙适配器**，或树莓派等自带蓝牙的机器） |
| 配对之后 | **手机不再需要**（App 可删可离线） | **配对机即可退役**，凭证导入常驻主机后它不再参与 |
| 运行 | MCP 进程按需连接，随 Mac 睡眠而断 | 云主机 systemd 常驻，24/7 在线 |
| SDK | [muse-client](https://github.com/wong2/muse-client)（社区 TS 移植，Apache-2.0） | 官方 [muse-gadget-sdk](https://github.com/facebookincubator/muse-gadget-sdk) linux/ |
| Muse 可执行本机命令 | ❌ 不注册任何本地命令（更安全） | ✅ `system.run` / `file.*`（可选裁剪） |
| 适合 | 日常开发机协作（90% 场景） | Mac 关机也要收发、想让 Muse 操作另一台机器 |

**选择建议**：先用路线 A，5 分钟打通；需要 24/7 或让 Muse 操作远端机器时，
再按路线 B 把凭证导入云主机，切 `backend: ssh`。

### 路线说明（重要）

- **路线 A：打通之后就不需要手机了。** 蓝牙只在配对那 2 分钟用一次；此后
  Mac 凭保存的凭证直连 Muse 云端 VM，Muse app 不用开着、可以离线、甚至
  卸载都不影响本 skill 收发（只要别在 app 里删除这台设备）。
- **路线 B：授权只需在一台 Linux 上获取一次，之后那台机器即可退役。**
  前提是这台**配对机**必须有蓝牙（云主机没有，需插 USB 蓝牙适配器；树莓
  派/笔记本自带即可）。凭证（`identity.json`+`pairing.json`）导入常驻主机
  后，配对机不再参与任何环节。

### Windows 也能用

两条路线都支持 Windows——核心原因是**配对凭证可跨机迁移**，而聊天运行时
本身是跨平台的：

| 场景 | 做法 |
|---|---|
| Windows 上跑**路线 A**（local） | 在任意 Mac（或 WSL2）配对一次 → 把凭证目录拷到 Windows → 配置 `credentials_dir` 指向它。macOS 配对机拷 `~/Library/Application Support/MuseGadgetPair/`；WSL2 配对机拷 `/var/lib/musegadget/`。运行需要 [bun](https://bun.sh)（或 Node ≥22.18）+ 仓库 `uv run` |
| Windows 上跑**路线 B**（ssh） | Windows 本身只当 MCP 客户端；gadget 主机仍是 Linux（WSL2 也行：musegadget 装在 WSL2 里，ssh 后端指向它），或按上表导入云主机 |

注意：配对工具本身仅支持 macOS（`pairMacOS`）与 Linux（官方 SDK），
**Windows 上无法直接配对**——所以是"借一台机器授权一次，之后 Windows
独立运行"。路线 A 的 Windows 聊天运行时未实测（依赖均为纯 JS，理论上
可用），遇到问题欢迎提 issue。

### 两种模式的能力差异（授权之外）

| 能力 | 路线 A · 手机配对（local） | 路线 B · Linux SDK（ssh） |
|---|---|---|
| 文字聊天 / 流式回复 | ✅ | ✅ |
| 发送图片（≤2 MiB） | ✅ | ✅ |
| 收 Muse 生成的图片 | ✅ 原生 ImageContent 内联显示 + 本地落盘（实测）；muse.ai 卡片 + COS 直链双通道 | ✅ 从回复文字解析直链（配 COS 中转最稳）；官方 CLI 收不到 presentation 卡片，ImageContent 同样可用 |
| Muse 执行本机命令（`system.run`/`file.*`） | ❌ 不注册任何命令 | ✅ 以安装账号权限执行，可经 `commands.d` 裁剪 |
| 语音通话（WAV/实时） | ❌（muse-client 未实现） | ⚠️ SDK 自带 `voice-call` CLI，未接入 MCP 工具 |
| 24/7 在线收发 | ❌ Mac 睡眠即断 | ✅ systemd 常驻 |
| 并发 | 单连接按需建立，**避免并发调用**（token 刷新冲突） | 服务端并发上限 4 命令；同一 chat 单等待 |
| 断连行为 | 链路直接断，无遗留 | **已开始的命令继续跑完**（官方行为） |

两条路线的 MCP 工具面基本一致（11 个工具），切换 `backend`
不需要改任何调用方式；仅 `muse_notifications` 为路线 A 专属（依赖本地
bridge 的被动监听）。

**路线 B 画图要走 COS 吗？——强烈建议。** 官方 CLI 只返回回复文本，
presentation 卡片和审批快照都拿不到：不配 COS 时只能指望 Muse 把
muse.ai/files 链接贴进回复文字（不稳定，逐文件审批照弹，等待审批在
CLI 侧表现为超时）；配 COS 后 Muse 上传你的 bucket 并把直链写进回复，
`muse_start_image_generation` / `muse_get_image_result` 在路线 B 下开箱
即用（首次仍需在 app 批一次 myqcloud 域名卡）。纯聊天、发图给 Muse
则不需要 COS。

### 多设备共享一台服务器

同一份凭证**不能**同时装在两台机器上（token 自动轮转会互相踩踏，同一设备
身份也会连接竞争）。多设备共用的正确姿势是路线 B：

```
设备1 (Mac)   ─┐
设备2 (家里PC) ─┼─ 各自装 skill，config: backend: ssh ──> 服务器（唯一持有凭证，24/7）
设备3 (公司)   ─┘
```

服务器跑 `provision.sh` + `import_state.sh` 持有授权；每台设备只需安装本
仓库并配好 `backend: ssh` + `host:`。你 Mac 上现有的路线 A 凭证就是官方
格式（`~/Library/Application Support/MuseGadgetPair/`），可直接交给
`import_state.sh` 导入服务器；导入后 Mac 侧建议停用本地后端，避免双机
共用同一凭证。

> 配对的本质：gadget 协议的认证锚点。Muse 只接受持有配对凭证（手机 app
> 经 BLE 扫到设备时签发的 `identity.json`/`pairing.json`）的设备。没有绕过
> 它的官方通道，但配对是一次性的 2 分钟操作。

## 二、配置步骤

> **选择你的路线**：[🅰 路线 A · 手机配对直连](#路线-a--手机配对直连默认推荐) ｜
> [🅱 路线 B · Linux SDK 常驻](#路线-b--linux-sdk-常驻)
>
> 也可以先跑一键向导 `scripts/setup.sh`（覆盖路线 A 全流程，逐项检查可重
> 跑），或在 agent 里随时调 `muse_doctor` 获取带命令的体检清单。

### 通用准备（两条路线都需要）

```sh
# 1. 仓库依赖
uv sync && uv run pytest              # Python 侧
cd bridge && bun install && cd ..     # Node 侧（需要 bun；Node ≥22.18 也可）

# 2. SDK Token（等同凭证，勿入 git、勿贴聊天）
#    https://gadgets.muse.ai/settings/sdk-tokens → Account → SDK tokens → 新建
mkdir -p ~/.config/muse-agent
echo 'mgst_你的token' > ~/.config/muse-agent/sdk_token && chmod 600 ~/.config/muse-agent/sdk_token
```

### 国内网络与代理（要不要开 TUN？）

**TUN 不是必须的。** 需要代理的只有两段，各有最省事的走法（海外网络
直连即可，跳过本节）：

| 阶段 | 谁要能访问 Meta 域名 | 最省事的走法 |
|---|---|---|
| 配对（一次性 2 分钟） | **手机 + 电脑**都要能访问 `hatch-api.meta.ai` | 怎么方便怎么来：手机开自己的代理；电脑开代理客户端的系统代理或 TUN 均可，配完就不用了 |
| 日常聊天/画图 | 只有**运行机**要通 `hatch.metaaivm.com`（手机不再参与） | **免 TUN、免系统代理**：`bridge_proxy` 一行 + proxychains4 按进程接管 |

日常这段的三个前提：

1. 代理客户端开着（Clash Verge / Surge / sing-box 均可），确认它的
   **SOCKS 端口**——Clash Verge 混合端口默认 `7897`，老版 Clash `7890`
2. `brew install proxychains-ng`（未装时自动回落 node 方案，但实测偶有
   空事件流，proxychains 优先）
3. 写一行配置（文件已有内容时确认末尾有换行、别粘连，同
   [docs/cos.md](docs/cos.md) 的翻车点说明）：

   ```sh
   mkdir -p ~/.config/muse-agent
   echo 'bridge_proxy: http://127.0.0.1:7897' >> ~/.config/muse-agent/config.yaml
   ```

原理一句话：MCP server 调 bridge 时自动生成 proxychains 配置，把 bun 的
全部连接（含 WSS）从 SOCKS5 出去——按进程接管，不碰系统网络；TUN 或
系统代理开着不冲突，不开也行。配对时段例外：`pair` 是手动命令，不走
这层包装，所以那 2 分钟用系统代理/TUN 最省事。

验证：`uv run muse-agent --status` 出 `ready: true` 即通；不通看下方
「五、排错」第一行。

---

### 路线 A · 手机配对直连（默认，推荐）

> 5 分钟打通。**手机只在配对那 2 分钟出场**（Muse app 经蓝牙确认这台
> 机器），之后彻底退役——App 可关、可离线、可卸载（只要别在 app 里
> 删除这台设备）。

**A1. 配对（一次性）**

> 这 2 分钟手机和电脑都要能访问 Meta 域名（见上方「国内网络与代理」），
> 配完手机就退役了。

```sh
export MUSE_SDK_TOKEN=$(cat ~/.config/muse-agent/sdk_token)
bun bridge/bridge.mjs pair
# 终端显示设备名（如 MuseGadget782C99）并开始 BLE 广播，然后拿手机：
#   Muse app → Settings → Devices → 开 Developer mode → Add Device (+)
#   → 选 MuseGadget782C99 → 确认 community 提示 → Wi-Fi 选 Use current connection
# 看到 "Paired successfully" 即完成；凭证存
#   ~/Library/Application Support/MuseGadgetPair/（勿删，token 自动刷新）
```

**A2. 验证**

```sh
bun bridge/bridge.mjs status          # 应返回 "paired": true, "ready": true
```

**A3.（推荐）配置 COS 图片中转——画图零审批弹窗**

Muse 官方 `muse.ai/files` 转存是**逐文件人工审批**（每张图弹一卡）；换成你
自己的 COS bucket（Mac 预签名、Muse 零凭证 curl 上传）后，**首次上传弹一次
域名审批卡，在 app 里选"永久允许"，此后终身零弹窗**。

**控制台一步步的操作手册（建桶怎么选、CAM 子账号密钥在哪建、配置文件
怎么写、自测与排错）见 [docs/cos.md](docs/cos.md)**——最终往
`~/.config/muse-agent/config.yaml` 加三行（文件已存在时务必另起一行，
追加粘连是最常见的翻车点）：

```yaml
cos_bucket_domain: muse-xxx.cos.ap-guangzhou.myqcloud.com   # 不带 https://
cos_secret_id: AKID…      # CAM 子账号的 API 密钥（别用主账号的）
cos_secret_key: …         # 32–36 位纯字母数字，创建时只显示一次
```

收尾两步：

4. 自测：`python3 skills/cos/cos.py selftest` → 看到 `selftest PASS`
   （PUT 200 + 匿名 GET 200）才算配好
5. 给 Muse 装 [muse-side/zcode-bridge](muse-side/README.md) 技能（zip 发进
   聊天即可）——不装的话 Muse 会无视预签名地址、退回官方转存
6. **首次让 Muse 上传时会弹一张审批卡**（`curl` 访问 myqcloud.com 的域名级
   审批）：在 Muse app 选**永久允许**即可。这是 COS 路线一生一次的手动审批，
   之后画图全程零弹窗——对比官方 muse.ai/files 路线每张图一卡

**A4. 注册 MCP + 安装 Skill**（见下方[通用收尾](#3-注册-mcp--安装-skill两条路线相同)）

---

### 路线 B · Linux SDK 常驻

> 24/7 在线。授权在**一台有蓝牙的 Linux** 上做一次（云主机没蓝牙，需插
> USB 蓝牙适配器；树莓派/笔记本自带即可），凭证导入常驻主机后**配对机
> 即可退役**。

**B1. 在配对机上配对**（一次性，之后这台机器不再需要）

任选：WSL2（Windows 侧 `usbipd` 直通 USB 蓝牙）或树莓派/Debian/Ubuntu：

```sh
sudo apt install -y bluez python3-dbus python3-gi      # WSL2 里可能还需蓝牙服务
curl -fsSL -o install.sh \
  https://raw.githubusercontent.com/facebookincubator/muse-gadget-sdk/main/linux/install.sh
less install.sh                                        # 先读一遍
sudo bash install.sh --sdk-token mgst_… --yes          # 安装官方 SDK
sudo musegadget pair                                   # 开 10 分钟配对窗口，手机 app 同 A1 操作
```

**B2. 导出凭证**（在配对机上）

```sh
sudo cp /var/lib/musegadget/{identity,pairing}.json ~/
sudo chown $USER ~/identity.json ~/pairing.json
scp identity.json pairing.json 你@Mac:~/muse-pairing/   # 拷到运行 MCP 的机器
```

**B3. 部署常驻主机**（在 Mac 上执行，`--dry-run` 可先预览）

```sh
scripts/provision.sh --host USER@云主机 --sdk-token $(cat ~/.config/muse-agent/sdk_token)
scripts/import_state.sh ~/muse-pairing --host USER@云主机
# 看到 systemd active + paired 即成功；之后长期运行全在云主机
```

**B4. 切换后端**（`~/.config/muse-agent/config.yaml`）

```yaml
backend: ssh
host: USER@云主机        # ssh 语法，IPv6 不带方括号

# 画图建议加 COS 中转（cos_* 三行，配置同路线 A3）：
# 官方 CLI 只回文本，直链写进回复文字是唯一稳定的取图通道
```

**B5. 验证 + 注册 MCP + 安装 Skill**

```sh
uv run muse-agent --status      # ready: true 即通；失败先跑 muse_doctor
```

注册见下方[通用收尾](#3-注册-mcp--安装-skill两条路线相同)。

---

### 3. 注册 MCP + 安装 Skill（两条路线相同）

仓库根已有 `.mcp.json`（打开仓库即被发现）。手动注册到客户端配置：

```json
{
  "mcpServers": {
    "muse": {
      "command": "uv",
      "args": ["--directory", "/path/to/muse-skill", "run", "muse-agent"]
    }
  }
}
```

Claude Code 一条命令：`claude mcp add muse -- uv --directory /path/to/muse-skill run muse-agent`
（详见 [docs/claude-code.md](docs/claude-code.md) / [docs/zcode.md](docs/zcode.md)）

安装 Skill（可选，让 agent 知道何时、怎么用 Muse）：

```sh
cp -r skills/muse ~/.agents/skills/muse      # Zcode
cp -r skills/muse ~/.claude/skills/muse      # Claude Code
# COS 上传技能（可选）：本机文件上传 COS 拿永久直链，复用同一份 cos_* 配置
cp -r skills/cos  ~/.agents/skills/cos       # 纯 stdlib，系统 python3 即可
```

## 三、使用方法

### 在 agent 里用（主要方式）

新开会话后直接说人话，agent 会调对应工具：

| 你说 | agent 调用 |
|---|---|
| 「查一下 Muse 在不在」 | `muse_status` |
| 「问 Muse：帮我分析这个 API 设计……」 | `muse_chat(message)` |
| 「把这张截图发给 Muse 看看」 | `muse_send_image(path, message)` |
| 「给 Muse 发个通知，不用等回复」 | `muse_send(message)` |
| 「让 Muse 画一张 xx 的图」 | `muse_start_image_generation(prompt)` → 拿 task_id → `muse_get_image_result(task_id)` 返回**原生 MCP 图片**（对话内直接显示）+ 本地路径；或一步到位 `muse_get_images(prompt)` |
| 「开个新会话专门讨论 X」 | `muse_sessions(label="X")` → 拿 `session_id` 后持续追问 |
| 「看看 Muse 有没有新通知」 | `muse_notifications(wait_seconds)` ← 被动收 Muse 主动推来的消息/图片（需先给 Muse 装 [muse-side/zcode-bridge](muse-side/README.md) 技能） |
| 「把这个文件/图片传到 COS 拿直链」 | [skills/cos](skills/cos/SKILL.md) 技能：`python3 ~/.agents/skills/cos/cos.py upload 文件 --md`（纯 stdlib、复用 cos_* 配置、直链永久） |

行为约定（agent 的 SKILL.md 已内置）：
- 首次会话先 `muse_status`；未配对会收到指向 `docs/pairing.md` 的引导
- `muse_chat` 默认走 **agent 专属 side chat**（自动创建的 UUID 会话），
  不污染你在 Muse app 里的主聊天
- **超时 ≠ 失败**：消息已送达，Muse 可能晚些回；加大 timeout 重试即可
- 图片限 2 MiB（JPEG/PNG/GIF/WebP）
- 让 Muse 画图：画图是异步任务。`muse_get_image_result` 返回**原生 MCP
  ImageContent**（客户端内联显示）+ 本地落盘路径（`~/.config/muse-agent/images/<task_id>/`）。
  超时 ≠ 失败：任务持久化，稍后再次轮询即可，**不会重新生成**。审批等待时
  状态为 `approval_required`，去 Muse app 批准后继续。仅 local 后端支持
- **外联审批**：让 Muse 跑外联任务时，Muse app 可能弹审批卡。普通域名卡选
  "永久允许"一次即好；画图转存走 **COS 中转：首次弹一次 myqcloud 域名卡，
  "永久允许"后零弹窗**（配置见路线 A3）；官方 muse.ai/files 路线是逐文件
  审批、每张图一卡。详见 [docs/auto-approve.md](docs/auto-approve.md)
- **给用户展示图片永远用 Markdown 语法** `![描述](直链)`，裸链接在会话里
  不渲染；优先用不过期的 COS 直链

### 直接用 CLI（调试 / 脚本）

```sh
bun bridge/bridge.mjs status                                  # 状态
bun bridge/bridge.mjs chat "你好" --timeout 120               # 发并等回复
bun bridge/bridge.mjs chat "继续" --session <uuid>            # 指定 side chat
bun bridge/bridge.mjs image pic.png "这是什么？" --timeout 120 # 图片+文字
bun bridge/bridge.mjs send "通知（不等回复）"                  # fire-and-forget
bun bridge/bridge.mjs images "画一只太空猫" --session <uuid>    # 生成并收集公网直链
uv run muse-agent --status                                    # MCP server 自检
```

## 四、配置参考

`~/.config/muse-agent/config.yaml`（全部可选，环境变量 `MUSE_AGENT_*` 优先）：

```yaml
backend: local          # local（默认，路线 A 手机配对直连）| ssh（路线 B 云主机常驻）
host: root@example.com  # backend: ssh 时的 gadget 主机
timeout: 120            # muse_chat 默认等待秒数（上限 600）
bridge_command: bun     # bridge/bridge.mjs 的运行器（node ≥22.18 也可）
bridge_proxy: http://127.0.0.1:7897  # 国内网络必配：免 TUN 走代理
#                          # （proxychains4+bun，brew install proxychains-ng）
# credentials_dir: …    # muse-client 凭证目录覆盖（默认 ~/Library/Application Support/MuseGadgetPair）

# COS 图片中转（推荐）：Mac 持密钥预签名，Muse 零凭证 curl 上传，
# 画图零审批弹窗、直链永久有效（配置步骤见路线 A3）
# cos_bucket_domain: muse-xxx.cos.ap-guangzhou.myqcloud.com
# cos_secret_id: AKID…      # 子账号（仅该 bucket 数据读写）
# cos_secret_key: …         # 36 位纯字母数字；只放本文件（.gitignore 已排除）
```

## 五、排错

| 症状 | 处理 |
|---|---|
| 配对卡在 Wi-Fi 之后 | 手机访问 `hatch-api.meta.ai` 不通，检查手机代理 |
| `certificate verification error` / WebSocket 连不上 | `hatch.metaaivm.com` 被断网/代理节点劣化——先 `curl -x 代理 http://127.0.0.1:PORT https://www.google.com` 验证节点，再在 config 配 `bridge_proxy: http://127.0.0.1:7897`（自动走 proxychains4 免 TUN，需 `brew install proxychains-ng`） |
| COS 上传 `403 SignatureDoesNotMatch` | `cos_secret_key` 不配对/被污染：自查应为 **36 位纯字母数字**（注意 config 追加内容别粘连到上一行），然后跑 A3 的自测命令，PUT 200 才算好 |
| Muse 无视预签名地址、仍走 muse.ai 转存 | 没装或没更新 [muse-side/zcode-bridge](muse-side/README.md) 技能——把 zip 发给 Muse 装上 |
| 首次 COS 上传弹了一张 myqcloud.com 审批卡 | **正常且仅此一次**：域名级 `tool.exec` 审批，在 app 选**永久允许**后终身不再弹（官方 muse.ai/files 路线才是每张图一卡，见 [docs/auto-approve.md](docs/auto-approve.md)） |
| `chat` 超时但 app 里能看到回复 | 消息发到了主聊天（回复无法归属被丢弃）——用 agent 默认 side chat 或显式 `--session <uuid>` |
| 同一会话反复超时、新会话秒回 | **会话积压**（高频自动化测试后常见）：该会话消息队列被塞满，旧会话慢慢消化，新会话立即响应——`muse_sessions` 开新会话重发即可（agent 的 SKILL.md 已内置此轮换规则） |
| Muse 拒画某题材（回复"这张没能画出来"） | Muse 自带内容审核，暴力类描述（如"打架"）会被拒，且它通常主动给出温和替代方案——接受替代或换个描述，别原样重发 |
| `HTTP 400` on side chat | Muse 只接受 **UUID 格式**的 session id，用 `muse_sessions` 生成 |
| 换了 SDK token 后连不上 | 凭证与签发时的 token 绑定：先 unpair 再重新 pair |
| ssh 后端不可达 | `scripts/provision.sh` 部署；`musegadget info` / `doctor` 排查 |
| 让 Muse 跑任务卡住无响应 | 看 Muse app 是否有**外联审批**卡片待批准；画图场景配 COS 中转可根除 |

安全：token 与凭证只在配对机上，永不入库；local 后端不给 Muse 任何本机
命令权限；ssh 后端下 Muse 获得安装账号的 `system.run`/`file.*` 能力，且
**断连不会取消已开始的命令**（官方行为）。完整说明见
[docs/pairing.md](docs/pairing.md)。

## 开发

```sh
uv run pytest            # 单测（无网络）
uv run muse-agent --status
bun bridge/bridge.mjs --help
```

```
src/muse_agent/
  server.py        MCP stdio server（11 个工具）
  adapter.py       统一 API + side chat/图片任务管理
  backend_local.py local 后端：bridge.mjs + 代理路由（proxychains/node 双方案）
  backend_ssh.py   ssh 后端：调远端 musegadget CLI
  tasks.py         图片任务注册表（持久化状态机）
  cosign.py        COS 预签名（纯 Python，无 SDK）
  ssh.py / config.py
bridge/bridge.mjs  muse-client 的 JSON CLI（pair/status/send/chat/image/notifications）
bridge/node-proxy.mjs  node+global-agent 代理运行器（proxychains 不可用时兜底）
muse-side/         发给 Muse 安装的 zcode-bridge 技能（zip）
skills/            Agent Skills：muse（Muse 工具用法）+ cos（本机文件传 COS）
scripts/           provision.sh / import_state.sh / setup.sh
```
