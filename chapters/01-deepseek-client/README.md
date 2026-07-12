# 配套代码 01：最小 DeepSeek 连续对话客户端

对应《RE:从零开始的大模型研究日记 01》。

这是一个运行在终端里的最小聊天客户端。它会在当前程序运行期间保存对话，并在每一轮请求时将历史消息一并发送给 DeepSeek。

可以先输入：

> 我的代号是海盐。

下一轮再问：

> 我的代号是什么？

模型能够回答“海盐”，说明连续对话已经正常工作。

## 需要准备

- Python 3.10 或更高版本
- DeepSeek 开放平台账户
- 一枚可用的 API Key
- 账户中有少量 API 余额
- 能正常访问 DeepSeek API 的网络

> API 会按实际 Token 用量计费。运行前请在 DeepSeek 开放平台查看最新价格。

## 本章文件

```text
chapters/01-deepseek-client/
├── main.py
├── requirements.txt
├── .env.example
└── README.md
```

仓库根目录的 `.gitignore` 会统一忽略各章节中的 `.env`、虚拟环境和 Python 缓存。

## macOS / Linux

从仓库根目录进入本章：

```bash
cd chapters/01-deepseek-client
```

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

打开 `.env`，将 `DEEPSEEK_API_KEY` 后面的示例内容替换为自己的 Key，然后运行：

```bash
python3 main.py
```

## Windows PowerShell

从仓库根目录进入本章：

```powershell
cd chapters/01-deepseek-client
```

创建虚拟环境并安装依赖：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
```

打开 `.env`，将 `DEEPSEEK_API_KEY` 后面的示例内容替换为自己的 Key，然后运行：

```powershell
py main.py
```

如果 PowerShell 阻止虚拟环境激活，可以仅对当前窗口执行：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 对话命令

- `/reset`：清空当前对话历史
- `/help`：查看命令说明
- `/exit`：退出程序

按 `Control + C` 也可以退出。

## 它为什么能记住上一轮

程序维护了一份 `messages` 列表。每次提问时，它会把系统提示、用户过去的提问和模型过去的回答一起发送给 API。

这里的“记忆”只存在于当前程序进程中：

- 输入 `/reset` 后会消失；
- 关闭程序后会消失；
- 它还不是长期记忆系统。

## 常见报错

### `ModuleNotFoundError: No module named 'openai'` 或 `dotenv`

依赖尚未安装，或者当前终端没有进入虚拟环境。重新激活虚拟环境，再运行：

```bash
python3 -m pip install -r requirements.txt
```

Windows 也可以使用：

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

确认 `.env` 中的模型名称与 DeepSeek 当前官方文档一致。

### 连接超时或 API Connection Error

检查 DeepSeek 开放平台、当前网络、代理和防火墙。程序会自动重试两次。

## 密钥安全

- 不要把真实 API Key 写进 `main.py`；
- 不要公开 `.env`；
- 不要在文章截图、录屏或日志中露出 Key；
- 如果 Key 已经泄露，请立即撤销并重新创建。

## 许可

本章代码沿用仓库根目录的 MIT License。第三方模型和 API 的使用仍需遵守相应服务提供方的条款。
