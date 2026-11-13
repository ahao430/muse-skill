# Muse Agent Skill

把 [Muse](https://muse.ai) 接入 coding agents（Claude Code / Zcode 等）：
通过 **MCP** + **Agent Skills**，让 agent 能向 Muse 发消息、收回答、发图片，
做跨 agent 协作。全链路本地，无公网服务器。**已端到端验证**（文字、新会话、
图片收发均实测通过）。

## 一、方案路线（两条，二选一或都配）

两条路线底层都是官方 **Gadget 协议**（WSS + Noise 加密会话直连 Muse VM），
区别只是"设备角色"跑在哪台机器上。**蓝牙只在配对那一刻用一次**，之后
手机彻底退出链路。

```
路线 A（Mac 直连，推荐）
  Claude Code / Zcode ──MCP stdio──> muse-agent（本仓库，Mac）
                                        │ backend: local（默认）
                                        ▼
                     muse-client（TS 移植，Mac 内置蓝牙配对一次）
                                        │ WSS + Noise（走互联网）
                                        ▼
                                     Muse VM

路线 B（Linux 常驻）
  Claude Code / Zcode ──MCP stdio──> muse-agent（Mac）
                                        │ backend: ssh
                                        ▼
                     musegadget systemd 服务（云主机/树莓派，24/7）
                                        │ WSS + Noise
                                        ▼
                                     Muse VM
```

| | 路线 A：local | 路线 B：ssh |
|---|---|---|
| 配对 | **Mac 本机**，内置蓝牙，零硬件 | 任意有 BLE 的 Linux（WSL2+USB 蓝牙 / 树莓派）配对一次，凭证导入云主机 |
| 运行 | MCP 进程按需连接，随 Mac 睡眠而断 | 云主机 systemd 常驻，24/7 在线 |
| SDK | [muse-client](https://github.com/wong2/muse-client)（社区 TS 移植，Apache-2.0） | 官方 [muse-gadget-sdk](https://github.com/facebookincubator/muse-gadget-sdk) linux/ |
| Muse 可执行本机命令 | ❌ 不注册任何本地命令（更安全） | ✅ `system.run` / `file.*`（可选裁剪） |
| 适合 | 日常开发机协作（90% 场景） | Mac 关机也要收发、想让 Muse 操作另一台机器 |

**选择建议**：先用路线 A，5 分钟打通；需要 24/7 或让 Muse 操作远端机器时，
再按方式二把凭证导入云主机，切 `backend: ssh`。

### 两种模式的能力差异（授权之外）

| 能力 | local（Mac 直连） | ssh（Linux gadget） |
|---|---|---|
| 文字聊天 / 流式回复 | ✅ | ✅ |
| 发送图片（≤2 MiB） | ✅ | ✅ |
| 收 Muse 生成的图片/文件卡片 | ❌ 只回传文本 | ❌ 只回传文本（SDK 层有 raw 事件，可扩展） |
| Muse 执行本机命令（`system.run`/`file.*`） | ❌ 不注册任何命令 | ✅ 以安装账号权限执行，可经 `commands.d` 裁剪 |
| 语音通话（WAV/实时） | ❌（muse-client 未实现） | ⚠️ SDK 自带 `voice-call` CLI，未接入 MCP 工具 |
| 24/7 在线收发 | ❌ Mac 睡眠即断 | ✅ systemd 常驻 |
| 并发 | 单连接按需建立，**避免并发调用**（token 刷新冲突） | 服务端并发上限 4 命令；同一 chat 单等待 |
| 断连行为 | 链路直接断，无遗留 | **已开始的命令继续跑完**（官方行为） |

两条路线的 MCP 工具面完全一致（`muse_chat` 等 7 个），切换 `backend`
不需要改任何调用方式。

> 配对的本质：gadget 协议的认证锚点。Muse 只接受持有配对凭证（手机 app
> 经 BLE 扫到设备时签发的 `identity.json`/`pairing.json`）的设备。没有绕过
> 它的官方通道，但配对是一次性的 2 分钟操作。

## 二、配置步骤

### 一键引导（推荐首次使用）

```sh
scripts/setup.sh
```

向导会逐步检查并跳过已完成项：Python/Node 依赖 → SDK token（就地粘贴，
不回显）→ 蓝牙配对（可选现场发起）→ 最终连接验证 + MCP 注册命令。

也可随时在 agent 里调 `muse_doctor`：返回逐项体检清单（运行器、bridge
脚本、依赖、凭证、连接），每一项缺失都给出**确切的下一步命令**。

### 手动步骤

```sh
# 仓库依赖
uv sync && uv run pytest              # Python 侧（23 个测试）
cd bridge && bun install && cd ..     # Node 侧（需要 bun；Node ≥22.18 也可）

# SDK Token（等同凭证，勿入 git、勿贴聊天）
#   https://gadgets.muse.ai/settings/sdk-tokens → Account → SDK tokens → 新建
#   得到 mgst_… 串；保存到本地文件（供配对脚本读取，不出现在终端历史里更佳）
mkdir -p ~/.config/muse-agent
echo 'mgst_你的token' > ~/.config/muse-agent/sdk_token && chmod 600 ~/.config/muse-agent/sdk_token
```

网络要求：配对时**手机**和 Mac 都要能访问 `hatch-api.meta.ai` /
`api.muse.ai`（国内网络可能需代理）。日常使用只需 Mac 能通。

### 1. 配对（一次性，路线 A）

```sh
export MUSE_SDK_TOKEN=$(cat ~/.config/muse-agent/sdk_token)
bun bridge/bridge.mjs pair
# 终端显示设备名（如 MuseGadget782C99）并开始 BLE 广播，然后拿手机：
#   Muse app → Settings → Devices → 开 Developer mode → Add Device (+)
#   → 选 MuseGadget782C99 → 确认 community 提示 → Wi-Fi 选 Use current connection
# 看到 "Paired successfully" 即完成；凭证存
#   ~/Library/Application Support/MuseGadgetPair/（勿删，token 自动刷新）

bun bridge/bridge.mjs status          # 验证：应返回 "paired": true, "ready": true
```

之后**手机不再参与任何环节**；Mac 睡眠/关机也不影响凭证，重开后自动重连。

路线 B 的 Linux 配对 + 凭证导入见 [docs/pairing.md](docs/pairing.md) 方式二
（`scripts/provision.sh` 一键部署云主机，`scripts/import_state.sh` 导入凭证）。

### 2. 注册 MCP server

仓库根已有 `.mcp.json`（打开仓库即被发现）。手动注册到客户端配置：

```json
{
  "mcpServers": {
    "muse": {
      "command": "uv",
      "args": ["--directory", "/Users/wanghao/workspace/muse-skill", "run", "muse-agent"]
    }
  }
}
```

Claude Code 一条命令：`claude mcp add muse -- uv --directory /path/to/muse-skill run muse-agent`
（详见 [docs/claude-code.md](docs/claude-code.md) / [docs/zcode.md](docs/zcode.md)）

### 3. 安装 Skill（可选，让 agent 知道何时、怎么用 Muse）

```sh
cp -r skills/muse ~/.agents/skills/muse      # Zcode
cp -r skills/muse ~/.claude/skills/muse      # Claude Code
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
| 「开个新会话专门讨论 X」 | `muse_sessions(label="X")` → 拿 `session_id` 后持续追问 |

行为约定（agent 的 SKILL.md 已内置）：
- 首次会话先 `muse_status`；未配对会收到指向 `docs/pairing.md` 的引导
- `muse_chat` 默认走 **agent 专属 side chat**（自动创建的 UUID 会话），
  不污染你在 Muse app 里的主聊天
- **超时 ≠ 失败**：消息已送达，Muse 可能晚些回；加大 timeout 重试即可
- 图片限 2 MiB（JPEG/PNG/GIF/WebP）

### 直接用 CLI（调试 / 脚本）

```sh
bun bridge/bridge.mjs status                                  # 状态
bun bridge/bridge.mjs chat "你好" --timeout 120               # 发并等回复
bun bridge/bridge.mjs chat "继续" --session <uuid>            # 指定 side chat
bun bridge/bridge.mjs image pic.png "这是什么？" --timeout 120 # 图片+文字
bun bridge/bridge.mjs send "通知（不等回复）"                  # fire-and-forget
uv run muse-agent --status                                    # MCP server 自检
```

## 四、配置参考

`~/.config/muse-agent/config.yaml`（全部可选，环境变量 `MUSE_AGENT_*` 优先）：

```yaml
backend: local          # local（默认，Mac 直连）| ssh（云主机常驻）
host: root@example.com  # backend: ssh 时的 gadget 主机
timeout: 120            # muse_chat 默认等待秒数（上限 600）
bridge_command: bun     # bridge/bridge.mjs 的运行器（node ≥22.18 也可）
# credentials_dir: …    # muse-client 凭证目录覆盖（默认 ~/Library/Application Support/MuseGadgetPair）
```

## 五、排错

| 症状 | 处理 |
|---|---|
| 配对卡在 Wi-Fi 之后 | 手机访问 `hatch-api.meta.ai` 不通，检查手机代理 |
| `chat` 超时但 app 里能看到回复 | 消息发到了主聊天（回复无法归属被丢弃）——用 agent 默认 side chat 或显式 `--session <uuid>` |
| `HTTP 400` on side chat | Muse 只接受 **UUID 格式**的 session id，用 `muse_sessions` 生成 |
| 换了 SDK token 后连不上 | 凭证与签发时的 token 绑定：先 unpair 再重新 pair |
| ssh 后端不可达 | `scripts/provision.sh` 部署；`musegadget info` / `doctor` 排查 |

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
  server.py        MCP stdio server（7 个工具）
  adapter.py       统一 API + side chat 管理（默认会话自动创建）
  backend_local.py local 后端：调 bridge/bridge.mjs
  backend_ssh.py   ssh 后端：调远端 musegadget CLI
  ssh.py / config.py
bridge/bridge.mjs  muse-client 的 JSON CLI（pair/status/send/chat/image）
scripts/           provision.sh（云主机部署）/ import_state.sh（凭证导入）
```
