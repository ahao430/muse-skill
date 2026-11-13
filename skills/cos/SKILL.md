---
name: cos
description: Upload local files to the user's Tencent COS bucket and get permanent public links. Use when the user asks to upload/host/share/publish a file or image, get a public URL for an asset, or back something up to cloud storage. Requires the cos_* fields in ~/.config/muse-agent/config.yaml.
---

# COS Upload Skill

One stdlib script (`cos.py`, next to this file) uploads files to the user's
COS bucket (public-read) and prints permanent public links. Credentials live
only in `~/.config/muse-agent/config.yaml` (shared with the muse skill) and
are never printed or sent anywhere else.

## Commands

```sh
# upload one or more files; prints one public URL per line
python3 <skill-dir>/cos.py upload 文件.png 另一个.pdf

# image destined for the chat — always render with Markdown (--md prints ![name](url))
python3 <skill-dir>/cos.py upload 图.png --md

# custom object key (default uploads/YYYYMMDD/<filename>)
python3 <skill-dir>/cos.py upload big.tar.zst --key backups/2026/big.tar.zst

# mint a share/upload URL without uploading; delete an object; health check
python3 <skill-dir>/cos.py presign some/key.png --expires 86400
python3 <skill-dir>/cos.py delete uploads/20260101/old.png
python3 <skill-dir>/cos.py selftest
```

`<skill-dir>` is where this skill is installed — `~/.agents/skills/cos`
(Zcode) or `~/.claude/skills/cos` (Claude Code). System `python3` is enough;
no dependencies, no activation, no server.

## Rules

- **Show uploaded images to the user as Markdown** (`![描述](直链)`, the
  `--md` output) — bare URLs do not render in the chat.
- **The bucket is public-read.** Only upload files the user actually wants
  publicly reachable; never upload secrets, credentials, or private data.
- Links are permanent (no expiry) — unlike presigned URLs, which expire
  (`presign --expires`, default 1 h) and are for handing out upload/download
  slots, not for sharing.
- Single-request PUT: fine up to ~1 GB in practice (COS hard limit 5 GB);
  no multipart.
- `403 SignatureDoesNotMatch` → `cos_secret_key` is wrong or glued to the
  previous line in config.yaml; run `selftest` after fixing (PUT 200 = good).
- Not configured? Tell the user to fill the three `cos_*` fields in
  `~/.config/muse-agent/config.yaml` (muse-skill README, route A3).
