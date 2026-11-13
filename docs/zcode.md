# Zcode 接入

## 注册 MCP server

在 Zcode 的 MCP 配置（设置 → MCP，或工作区 `.mcp.json`）中加入：

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

## 安装 Skill（可选）

```sh
mkdir -p ~/.agents/skills
cp -r skills/muse ~/.agents/skills/muse
```

## 验证

1. 新开一个 Zcode 会话（让 MCP 配置生效）
2. 「查一下 muse 状态」→ `muse_status`
3. 配对完成后：「帮我问 Muse …」→ `muse_chat`

## 无 MCP 时的手动调试

```sh
uv run muse-agent --status   # 直接打印 gadget host 状态 JSON
```
