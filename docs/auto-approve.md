# Muse 外联审批（HITL）与自动批准

## 现象：让 Muse 跑任务时"卡住不动"

Muse 的 Agent VM 执行需要访问外网的任务（`npm install`、`curl`、上传文件
到公网……）时，如果目标域名没有放行规则，**Muse app 会弹出审批卡片**
（human-in-the-loop），等你批准后任务才继续。如果你不盯着 app，任务就会
一直 pending——这是"让 Muse 干活卡在授权"的真正原因，**与 gadget/skill
这侧的配对授权无关**。

好消息：审批规则是**按域名持久化的**。同一域名批准一次（选"永久允许"）
之后就不再弹单。

## 方式 A（推荐，零工具）：手动批准一次

1. 让 Muse 执行任务（例如 `muse_get_images` 触发画图/转存）
2. 打开 **Muse app**，会看到外联审批卡片，显示目标域名
3. 选择**永久允许**（allow_always，按目标域名落库）
4. 任务自动继续；同域名以后不再弹单

需要批准的常见域名（按需）：`muse.ai`、`registry.npmjs.org`、你的 COS
bucket 域名（`*.cos.*.myqcloud.com`——配置了 COS 图片中转后，**首次上传**
会弹这一张，选"永久允许"后画图终身零弹窗）、你让它访问的任何站点。
适合个人使用——弹几次就全放行完了。

> 两类审批别混淆：**muse.ai/files 官方转存**是逐文件审批（每张图一卡，
> 没有"永久允许"选项）；**COS 中转**是域名级审批（一生一次，allow_always）。
> 这正是推荐 COS 中转的原因。

## 方式 B：全自动批准器 muse-auto-approve

社区项目 [caichengle666/muse-auto-approve](https://github.com/caichengle666/muse-auto-approve)
（逆向复刻 muse.ai 客户端协议）：在你自己机器上跑一个 Node 守护进程，实时
轮询审批单并对新域名自动 `allow_always`，带登录自愈与会话保活（30 天内
跑过一次即永续）。

**它安装在哪里？** 不是装在 Muse 端——装在**任何你能长期开机的机器**
（你的 Mac / 服务器均可），它以你的账号身份连上 Muse 网关代你点批准。

### 步骤（在你自己的机器上）

```sh
# 前置：Node.js ≥ 20.18（建议 22 LTS）；需要代理时 export MUSE_PROXY=http://127.0.0.1:7890
git clone https://github.com/caichengle666/muse-auto-approve.git
cd muse-auto-approve && npm install

# 凭据：环境变量或 data/credentials.json（chmod 600）
export MUSE_USER=you@example.com MUSE_PASSWORD='your-password'

node muse-daemon.cjs --check      # 体检（本地，不出网）
node muse-daemon.cjs --smoke      # 真测一次自动登录链路（会发一封验证邮件，无需读码）
node muse-daemon.cjs              # 常驻：10s 轮询 + allow_always + 保活
bash keepalive.sh --install-cron  # 可选：cron 保活（死了自动拉起）
```

### 或者：让 Muse 代办（不碰命令行）

在 Muse app 开浏览器模式，把项目链接发给它：

```
https://github.com/caichengle666/muse-auto-approve/blob/main/SKILL.md
请按这个 skill 帮我把自动审批跑起来
```

Muse 会照 SKILL.md 自己完成部署（⚠️ 凭据传递见下方安全须知）。

## 安全须知（方式 B 必读）

- `allow_always` 会**削弱 Muse 的人工审批保护**：任何新域名都自动放行。
  只在你能接受这个风险时使用；更稳妥的折中是 `--decision allow_session`。
- 该项目是**第三方逆向实现**，需要你提供 muse.ai 邮箱+密码。仅在你信任
  的机器上运行；凭据走环境变量或 0600 文件，不要发到聊天/git。
- 与本 skill 的关系：完全可选。路线 A/B 的聊天、图片收发不依赖它；只有
  "让 Muse 执行外联任务"且不想手动点批准时才需要。

## 排错速查

| 症状 | 处理 |
|---|---|
| `muse_get_images` / 生成任务长时间无响应 | 先看 Muse app 是否有审批卡片待批准（方式 A 手动放行） |
| 任务里 Muse 说"等待确认/审批" | 同上 |
| daemon 反复重登 | 检查 `MUSE_PROXY` 与账号；`node muse-daemon.cjs --check` |
| 连续登录失败熔断（exit 3） | 核对凭据后 `node work/login-lib.cjs` 解除 |
