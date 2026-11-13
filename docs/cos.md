# COS 图片中转配置手册（从零到零弹窗）

目标：花 10 分钟拿到三个值，写进一个配置文件，此后让 Muse 画图
**零审批弹窗、直链永久有效**（对比官方 muse.ai/files 转存：每张图弹一次卡）。

先说清要拿什么——

| 配置项 | 是什么 | 长什么样 |
|---|---|---|
| `cos_bucket_domain` | 你的存储桶访问域名（**不带 `https://`**） | `muse-1318404118.cos.ap-guangzhou.myqcloud.com` |
| `cos_secret_id` | 子账号 API 密钥 ID | `AKID` 开头，约 36 位 |
| `cos_secret_key` | 子账号 API 密钥 Key | 32–36 位纯字母数字，**只显示一次** |

密钥只放在本机 `~/.config/muse-agent/config.yaml`（该文件在 home 目录，
天然不在任何 git 仓库里）；Muse 那侧永远只收到 1 小时有效的预签名地址，
**零凭证过境**。

---

## 第 1 步：创建存储桶（公有读私有写）

1. 登录 [腾讯云控制台](https://console.cloud.tencent.com)（需实名认证），
   顶部搜索「**对象存储**」→ 左侧「存储桶列表」→「**创建存储桶**」
2. 按下表选（画图直链场景的最优解，也是最便宜的组合）：

   | 选项 | 选什么 | 说明 |
   |---|---|---|
   | 名称 | 如 `muse-media`（随意） | 创建后自动拼上 APPID 后缀，全局唯一 |
   | 地域 | 就近，如 `ap-guangzhou` | 决定域名中段 |
   | 访问权限 | **公有读私有写** | 图片要能直链打开必须公有读；写入走密钥 |
   | 多AZ | **关闭** | 多 AZ 翻倍贵，画图场景毫无必要 |
   | 存储类型 | **标准存储** | 低频/归档有最短存储时长和取回费 |
   | 服务端加密 | **不开启** | 加密对象对直链展示无益 |

3. 创建后进桶的「**概览**」页，找到「访问域名」，形如
   `muse-1318404118.cos.ap-guangzhou.myqcloud.com`
   ——这就是 `cos_bucket_domain`（去掉 `https://` 前缀，只要裸域名）。

## 第 2 步：CAM 子账号 + API 密钥（不要用主账号密钥）

主账号密钥权限太大，泄漏即全线失守；我们建一个**只能读写这个桶**的子账号：

1. 控制台搜索「**访问管理 CAM**」→ 左侧「用户」→「用户列表」→「**新建用户**」
   → 选「**自定义创建**」→ 访问方式勾「编程访问」
2. 设置权限：在策略列表搜索 `QcloudCOSDataReadWrite`
   （对象存储**数据**读写），勾选它即可——不给 FullAccess，更不给
   AdministratorAccess
3. 创建完成页会显示 `SecretId` 和 `SecretKey`——**SecretKey 只显示这一次**，
   立刻复制保存（丢了只能重新生成）

> 忘了复制/怀疑泄漏：用户详情 → 「安全设置」→ API 密钥，随时禁用重建。

## 第 3 步：写配置文件

文件是 `~/.config/muse-agent/config.yaml`，**扁平的 `键: 值` 三行**。

**文件还不存在**（全新安装）——一条命令建好：

```sh
mkdir -p ~/.config/muse-agent
cat > ~/.config/muse-agent/config.yaml <<'EOF'
cos_bucket_domain: muse-131xxxxxxxxx.cos.ap-guangzhou.myqcloud.com
cos_secret_id: AKIDxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
cos_secret_key: xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
EOF
chmod 600 ~/.config/muse-agent/config.yaml
```

**文件已存在**（比如已配过 `bridge_proxy`）——用编辑器打开，**另起一行**
再加这三行：

```sh
nano ~/.config/muse-agent/config.yaml   # 或 vim / VS Code
```

⚠️ **最常见的翻车点**（真实案例）：用 `echo '...' >> config.yaml` 追加时
上一行没有换行符，新内容直接粘在旧值后面——`cos_secret_key` 变成 67 位的
畸形串，所有上传报 `403 SignatureDoesNotMatch`，而且肉眼很难看出来。
所以：追加前先 `tail -c 1` 确认文件以换行结尾，或者干脆用编辑器。

三个自查点：

- 域名**不带** `https://`，不含路径
- key 是 32–36 位**纯字母数字**（没有空格、引号、换行）
- `tail -1 config.yaml` 能完整打出最后一行（没被截断粘贴）

## 第 4 步：自测（必做）

```sh
python3 skills/cos/cos.py selftest
# 期望输出：
#   PUT 200, public GET 200
#   deleted uploads/selftest.txt
#   selftest PASS
```

- `PUT 200`：签名算法与密钥正确
- `public GET 200`：桶确实是公有读（直链能匿名打开）
- 任何一步不对 → 看下方排错表，改完重跑

## 第 5 步：给 Muse 装桥 + 首次批一次

1. 把仓库里的 `muse-side/zcode-bridge.zip` 发进与 Muse 的聊天并附安装
   提示词（见 [muse-side/README.md](../muse-side/README.md)）——不装的话
   Muse 会无视预签名地址、退回官方逐文件审批
2. 首次让 Muse 上传时会弹**一张** myqcloud.com 域名审批卡，在 Muse app 选
   「永久允许」——此后终身零弹窗（详见
   [docs/auto-approve.md](auto-approve.md)）

## 排错

| 症状 | 原因与处理 |
|---|---|
| `403 SignatureDoesNotMatch` | 密钥被污染：九成是**追加时粘连上一行**或复制带空格。打开文件逐行检查（key 应为 32–36 位纯字母数字），改完重跑 selftest |
| PUT 200 但浏览器打开直链 403 | 桶不是公有读：存储桶「权限管理」→ 验证公有读私有写 |
| PUT 报 `403 AccessDenied`（不是 SignatureDoesNotMatch） | 子账号没权限：CAM 里该用户是否绑了 `QcloudCOSDataReadWrite`；密钥是不是这个子账号的（主账号密钥别用） |
| 域名解析失败 / `Could not resolve host` | `cos_bucket_domain` 填错：不带 `https://`、APPID 后缀别漏（控制台概览页照抄） |
| 想换桶 / 换密钥 | 直接改 config.yaml 三行 + selftest；旧对象不受影响 |

## 费用量级

标准存储约 ¥0.1/GB/月，外网下行流量约 ¥0.5/GB。一张 webp 几百 KB，
画一百张图的全部成本大约几分钱——可以忽略，但桶别开多 AZ / 归档即可。

---

配好之后：agent 里说「让 Muse 画一张 xx」走
`muse_start_image_generation` → `muse_get_image_result`；本机文件上传拿
直链用 [skills/cos](../skills/cos/SKILL.md)（`python3 …/cos.py upload 文件 --md`）。
