# zcode-bridge：Muse 侧通知技能

参考 QQ 官方桥（qq_official_bot_bridge）的机制，为 Muse ↔ Zcode 做的
极简版：**Muse 主动把结果/图片/任务状态发到 agent 专用侧聊会话，Zcode 用
`muse_notifications` 工具被动收取**。

## 为什么不需要 daemon

QQ 桥需要 daemon + hook，是因为消息从外部平台进来需要常驻进程收。而
这里消息的发起者就是 **Muse 自己**——它按协议在会话里说话即可；
Zcode 侧的 muse-client 订阅天然就是接收端。Muse 侧因此只需要一份
**协议约定**（SKILL.md），零依赖、零进程。

## 第 1 步：把技能发给 Muse 安装

把 `zcode-bridge.zip`（或直接把 `SKILL.md`）发给 Muse，附这句话：

```
请把附件里的 zcode-bridge 技能安装到你的工作区
（~/workspace/skills/zcode-bridge/），读完 SKILL.md 后按其协议工作：
今后凡是要通知 Zcode 的结果/图片/任务状态，都按协议格式发到
muse-agent 开头的侧聊会话里。
```

也可以走链接方式（需 Muse 开浏览器模式）：

```
请按 https://github.com/ahao430/muse-skill/blob/main/muse-side/zcode-bridge/SKILL.md
安装 zcode-bridge 技能并确认你理解了通知协议。
```

## 第 2 步：Zcode 侧收取

agent 里直接说「看看 Muse 有没有新通知」→ 调用 `muse_notifications`：

- 被动监听 `wait_seconds`（默认 8s，上限 60s）：不发消息，只收 Muse
  在窗口内推来的文本消息 + muse.ai/files 图片链接
- 图片自动下载到 `~/.config/muse-agent/images/notifications/` 并以
  原生 MCP ImageContent 内联返回
- 跨轮询去重（`notifications-seen.json`），同一条不会重复交付

## 协议摘要（Muse 侧遵守）

- 发到 muse-agent 开头的侧聊会话（Zcode 创建的那个）
- 文本直接写；图片先 `files.upload` 转存为 muse.ai/files 链接再贴
- 结构化通知可用可选头：
  `[zcode-notify] type: task-done|task-failed|info|image` + 正文

## 已知限制（诚实声明）

- **无回放**：Muse 只在 Zcode 监听窗口内说的话能被收到；两边都不在线时
  发的消息会错过（弥补：重要任务用 `muse_start_image_generation` 走任务
  轨道，那条轨道有轮询补偿）
- 图片转存仍可能触发逐文件的上传审批（remote_storage / allow_once），
  需在 Muse app 批准；见 docs/auto-approve.md
- 仅 local 后端支持
