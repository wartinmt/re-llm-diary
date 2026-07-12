# 配套代码 01：最小 DeepSeek 连续对话客户端

对应《RE:从零开始的大模型研究日记 01》。这是一个运行在终端里的最小聊天客户端：它会把当前会话保存在程序内存中，并在每一轮请求时将历史消息一并发给 DeepSeek。

完成配置后，可以先输入：

> 我的代号是海盐。

下一轮再问：

> 我的代号是什么？

模型能够回答“海盐”，说明连续对话已经正常工作。

## 你需要准备

- Python 3.10 或更高版本
- DeepSeek 开放平台账户
- 一枚可用的 API Key
- 账户中有少量 API 余额
- 能正常访问 DeepSeek API 的网络

> API 会按实际 Token 用量计费。运行前请在 DeepSeek 开放平台查看最新价格。

## 项目文件

```text
re-llm-diary-code-01/
├── main.py            # 主程序
├── requirements.txt   # Python 依赖
├── .env.example       # 配置模板
├── .gitignore         # 防止密钥被提交
└── README.md
```

## macOS / Linux

在终端进入项目目录，然后执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

用任意文本编辑器打开 `.env`，将 `DEEPSEEK_API_KEY` 后面的示例内容替换为自己的 Key，然后运行：

```bash
python3 main.py
```

## Windows PowerShell

在 PowerShell 中进入项目目录，然后执行：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

用记事本或其他文本编辑器打开 `.env`，将 `DEEPSEEK_API_KEY` 后面的示例内容替换为自己的 Key，然后运行：

```powershell
py main.py
```

如果 PowerShell 阻止虚拟环境激活，可以仅对当前窗口执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

然后重新运行激活命令。

## 对话命令

- `/reset`：清空当前对话历史
- `/help`：查看命令说明
- `/exit`：退出程序

按 `Control + C` 也可以退出。

## 它为什么能记住上一轮

程序维护了一份 `messages` 列表。每次提问时，它会把系统提示、用户过去的提问和模型过去的回答一起发送给 API。

因此，这里的“记忆”只存在于当前程序进程中：

- 输入 `/reset` 后会消失；
- 关闭程序后会消失；
- 它还不是长期记忆系统。

这正是后续章节会继续处理的问题。

## 常见报错

### `ModuleNotFoundError: No module named 'openai'` 或 `dotenv`

依赖尚未安装，或当前终端没有进入项目的虚拟环境。重新执行本系统对应的虚拟环境激活命令，再运行：

```bash
python3 -m pip install -r requirements.txt
```

Windows 中也可以使用：

```powershell
py -m pip install -r requirements.txt
```

### `没有找到 DEEPSEEK_API_KEY`

确认：

1. 已将 `.env.example` 复制为 `.env`；
2. `.env` 与 `main.py` 位于同一目录；
3. Key 填在 `DEEPSEEK_API_KEY=` 后面；
4. 没有继续使用示例文字。

### `401` 或 Authentication Error

API Key 无效、已撤销或复制不完整。回到 DeepSeek 开放平台重新创建 Key，并更新 `.env`。

### `402` 或余额相关提示

账户余额不足。充值后重新请求。

### `404`、模型不存在或模型名称错误

确认 `.env` 中为：

```text
DEEPSEEK_MODEL=deepseek-v4-flash
```

模型名称可能随官方更新变化，可查看下方官方文档。

### 连接超时或 API Connection Error

先确认浏览器能访问 DeepSeek 开放平台；再检查代理、防火墙和当前网络。程序会自动重试两次。

### 安装依赖时提示找不到 `python3`

macOS 可先执行 `python3 --version`；Windows 通常使用 `py --version`。如果都找不到，需要先从 Python 官方渠道安装 Python 3。

## 密钥安全

- 不要把真实 API Key 写进 `main.py`；
- 不要公开 `.env`；
- 不要在文章截图、录屏或日志中露出 Key；
- 如果 Key 已经泄露，请立即在 DeepSeek 开放平台撤销并重新创建。

项目中的 `.gitignore` 已默认忽略 `.env`，但在提交代码前仍应手动检查一次。

## 当前接口信息

本项目于 **2026-07-12** 按 DeepSeek 官方 API 文档整理：

- Base URL：`https://api.deepseek.com`
- 模型：`deepseek-v4-flash`
- 接口格式：OpenAI-compatible Chat Completions
- 思考模式：显式设置为 `disabled`

旧名称 `deepseek-chat` 和 `deepseek-reasoner` 已被官方标记为将在 2026-07-24 停用，因此本项目不再使用旧名称。

官方文档：

- https://api-docs.deepseek.com/
- https://api-docs.deepseek.com/api/create-chat-completion/
- https://api-docs.deepseek.com/guides/thinking_mode/

## 许可

此配套示例代码采用 MIT License，可自由学习、修改和分发。请自行遵守 DeepSeek API 的服务条款。
