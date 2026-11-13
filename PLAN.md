可以，而且我更推荐你采用这种方式：**把 Muse MCP Server 作为 Skill 项目的一部分，随 Skill 一起安装和运行，不部署独立的远程 MCP 服务。**

不过需要区分两个概念：

- Skill：告诉 Claude Code、Zcode 等 Agent 如何使用 Muse。
- MCP Server：真正负责调用 Muse 官方 SDK、收发消息和执行工具。

两者可以放在同一个 Git 仓库、同一个 Python 项目中，但它们不是同一个东西。

## **1. 推荐架构：本地 Skill + 本地 MCP**

**Claude Code / Zcode / Codex**

Agent 客户端

**Muse Skill**

SKILL.md · 使用说明 · 工作流 · 场景指导

**Muse MCP Server**

本地 Python 进程 · stdio 通信 · MCP Tools

**Muse 官方 Linux SDK**

设备配对 · 会话管理 · 消息收发 · Gadget 命令

**Muse 官方服务 / Muse VM**

运行时的关系：

1. Agent 启动时，根据 MCP 配置启动本地 Python 进程。
2. Python 进程加载 Muse 官方 SDK。
3. SDK 与 Muse 建立连接。
4. Agent 通过 MCP 调用 Muse。
5. 不需要你额外维护 Web 服务、数据库或者云端中转服务。

这里的本地 MCP 进程虽然不是独立部署的服务器，但它仍然是一个需要运行的后台进程。

**唯一需要注意的是：运行 MCP 的机器必须具备 Muse SDK 所需的设备连接和配对环境。** 如果官方 SDK 依赖 BLE，那么不能简单假定在任意云主机上都能直接连接 Muse。

## **2. 需要特别注意：官方 SDK 的运行环境**

我进一步核对了官方 Linux SDK 文档，这里需要修正一个容易混淆的地方：

官方 Linux SDK 不是普通的 Python 客户端库，而是一个完整的 Gadget 设备实现。

它需要：

- Linux 系统（Debian 11+、Ubuntu 22.04+ 等）。
- Bluetooth LE，用于首次配对。
- Muse SDK Token。
- 与 Muse VM 建立加密连接。

而且官方 SDK 自带持续运行的 `musegadget` 服务。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



所以有两种部署方式：

| 方式    | MCP 位置   | Muse SDK 位置 |
| ----- | -------- | ----------- |
| A：一体化 | Linux 本机 | 同一台 Linux   |
| B：分离式 | Mac 本地   | Linux 小主机   |

**我建议第一版优先支持 A。**

如果你主要在 Mac 上使用 Claude Code、Zcode，那么可以采用 B：Agent 的 Skill 和 MCP 运行在 Mac，Linux 小主机负责 Muse Gadget 通信。两者之间用 SSH 调用受控接口。

这仍然不需要部署公网服务器，但确实需要一个常驻的 Linux Gadget 节点。

## **3. MCP 应该如何集成到 Skill？**

建议使用标准的 MCP stdio 模式。

例如项目安装后，Agent 配置：

```
{
  "mcpServers": {
    "muse": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/muse-agent-skill",
        "run",
        "muse-agent"
      ]
    }
  }
}
```

实际使用时：

- Agent 启动 MCP 子进程。
- MCP 子进程读取本地配置。
- 调用 Muse SDK 或本地 Gadget 接口。
- Agent 通过 MCP 获取结果。
- Agent 退出后，MCP 子进程也可以退出。

这就不需要额外的 HTTP API 服务。

注意：MCP 配置通常由 Agent 客户端管理，Skill 本身不能自动保证所有客户端都注册 MCP。我们需要在安装文档中分别提供 Claude Code、Zcode 等客户端的配置方法。

## **4. MCP 工具设计**

第一版不要把工具做得太多，建议先定义这些接口：

| 工具                | 参数                 | 说明            |
| ----------------- | ------------------ | ------------- |
| `muse_send`       | message、session_id | 发送消息给 Muse    |
| `muse_wait`       | request_id、timeout | 等待 Muse 回复    |
| `muse_chat`       | message、session_id | 发送并等待完整回复     |
| `muse_history`    | session_id、limit   | 获取会话历史        |
| `muse_status`     | 无                  | 查询连接状态        |
| `muse_sessions`   | 无                  | 查询可用会话        |
| `muse_send_image` | image_path、message | 发送图片给 Muse 分析 |

这里建议保留 `send` 和 `wait` 两个独立工具，同时提供组合工具 `chat`。

原因是有些任务需要等待较长时间，Agent 不应该因为一个同步调用一直阻塞。

另外，官方 SDK 的 `MuseTurn` 可以跟踪请求与回复事件，但需要正确处理消息确认、会话 ID 和回复归属。主聊天中的并发消息尤其需要注意串线问题，优先采用独立 side chat。

[image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

GitHub+1



### **关于画图、需求分析和远程执行**

这三个不一定需要分别实现底层 SDK：

- `muse_analyze`：可以作为 Skill 工作流，调用 `muse_chat`。
- `muse_draw`：通过 Muse 对话请求图片生成，再处理图片结果。
- `muse_remote_exec`：第一版建议由 Agent 自己调用授权的 SSH 工具；后续再研究 Muse Gadget 的命令回传机制。

这样不会把 Muse 本身的能力和 Agent 的能力混为一谈。

## **5. Skill 项目目录**

我建议最终采用这样的结构：

```

muse-agent-skill/
├── pyproject.toml
├── README.md
├── LICENSE
│
├── .mcp.json
│
├── skills/
│   └── muse/
│       └── SKILL.md
│
├── src/
│   └── muse_agent/
│       ├── __init__.py
│       ├── cli.py
│       ├── server.py
│       ├── config.py
│       │
│       ├── adapters/
│       │   └── muse_sdk.py
│       │
│       ├── services/
│       │   ├── chat.py
│       │   ├── session.py
│       │   ├── history.py
│       │   └── image.py
│       │
│       └── tools/
│           ├── chat.py
│           ├── status.py
│           ├── history.py
│           └── image.py
│
├── config/
│   └── config.example.yaml
│
├── docs/
│   ├── installation.md
│   ├── claude-code.md
│   ├── zcode.md
│   ├── architecture.md
│   └── security.md
│
└── tests/
    ├── test_chat.py
    ├── test_session.py
    └── test_mcp.py

```

## **6. 安全与配置**

建议配置文件放在用户目录，不要写入 Skill 仓库：

```
muse:
  sdk_token_env: MUSEGADGET_SDK_TOKEN
  state_dir: ~/.config/muse-agent
  default_timeout: 120

agent:
  default_session: main
  enable_image: true
  enable_remote_exec: false

security:
  require_confirmation: true
  allowed_tools:
    - chat
    - history
    - status
```

特别注意：

1. 不要把 SDK Token 提交到 Git。
2. 不要让普通聊天工具直接获得任意 Shell 执行权限。
3. 远程执行与文件写入必须独立授权。
4. 长任务需要超时、取消和结果关联机制。
5. 不要假设断开连接后，正在执行的任务会自动取消。官方文档明确说明部分命令会继续运行。

   [image](https://www.google.com/s2/favicons?domain=https://github.com\&sz=32)

   GitHub



## **7. 开发路线**

| 阶段 | 开发内容       | 验收标准                |
| -- | ---------- | ------------------- |
| P0 | 官方 SDK 适配  | 成功连接 Muse           |
| P1 | MCP Server | Agent 能调用 Muse      |
| P2 | Skill 工作流  | 需求分析、多轮对话           |
| P3 | 图片能力       | 图片发送及结果回传           |
| P4 | 远程主机       | 受控执行、结果回传           |
| P5 | 多 Agent 兼容 | Claude Code、Zcode 等 |

## **8. 项目定位和命名**

我建议：

# **Muse Agent**

推荐项目名

**Description**

Connect Muse AI to coding agents through MCP and Agent Skills. Enable cross-agent conversations, task analysis, image generation and remote device collaboration.

**技术定位**

- Python
- Official Muse Gadget SDK
- MCP Python SDK
- Agent Skills
- Local-first architecture

  GitHub Repository

  &#x20;复制名称

  muse-agent

**最后，我想强调一个架构原则：**

不要让 Skill 直接依赖某个 Agent，也不要让 MCP 依赖某个 Agent 的内部实现。

把它做成一个独立的 Python 包，Skill 只是它的使用指南。

这样以后不管是 Claude Code、Zcode、Codex，还是你自己开发的 AI 工作台，只要支持 MCP，就可以复用 Muse 的能力。

我认为这比单纯开发一个 Claude Code 专用 Skill 更有长期价值。
