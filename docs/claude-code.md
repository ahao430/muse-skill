# Claude Code 接入

## 注册 MCP server

```sh
claude mcp add muse -- uv --directory /Users/wanghao/workspace/muse-skill run muse-agent
```

或写入项目 `.mcp.json` / `~/.claude.json`：

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

## 安装 Skill（可选，推荐）

让 Claude Code 自动知道何时、如何使用 Muse 工具：

```sh
mkdir -p ~/.claude/skills
cp -r skills/muse ~/.claude/skills/muse
```

## 验证

1. 重启 Claude Code 会话
2. 输入「查一下 muse 状态」→ 应调用 `muse_status`
3. 配对完成后：「问一下 Muse 今天适合干什么」→ `muse_chat`
