# 配套代码 02：排错手册

先从最小范围开始，不要一遇到报错就删除全部文件重装。

## A. 程序根本没有启动

### `python3: command not found` 或 `py: command not found`

Python 没有安装，或终端还没有识别新安装的 Python。

- macOS：安装 Python 3 后，完全退出并重新打开终端，再执行 `python3 --version`。
- Windows：安装时勾选 `Add python.exe to PATH`，重新打开 PowerShell，再执行 `py --version`。

### `can't open file 'main.py'`

当前目录不对。

先列出文件：

- macOS / Linux：`ls -la`
- Windows PowerShell：`Get-ChildItem -Force`

当前目录中必须直接看到 `main.py`。

## B. 程序启动，但缺少 Python 包

### `No module named 'openai'` 或 `dotenv`

虚拟环境没有激活，或依赖没有安装。

macOS / Linux：

```bash
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
```

## C. 自检通过，但配置检查失败

### `没有找到 DEEPSEEK_API_KEY`

确认：

1. 已将 `.env.example` 复制为 `.env`；
2. 文件名不是 `.env.txt`；
3. `.env` 与 `main.py` 在同一目录；
4. Key 填在 `DEEPSEEK_API_KEY=` 后；
5. 没有保留示例文字；
6. 没有把 Key 放进中文引号。

### `DEEPSEEK_PRICE_... 不是有效数字`

价格只能填写普通数字，例如：

```text
0.0028
0.14
0.28
```

不要填写 `$`、逗号或“每百万”等文字。

## D. 配置检查通过，但真实请求失败

### 401 / Authentication Error

Key 错误、被撤销或复制不完整。重新创建 Key，并更新 `.env`。

### 402 / Insufficient Balance

账户没有可用余额。充值后重试。

### 404 / Model Not Found

检查 `.env` 中的模型名，并以官方当前文档为准。

### 422 / Invalid Parameters

本地 SDK 或接口字段可能已变化。先更新依赖：

```bash
python3 -m pip install -U -r requirements.txt
```

Windows 使用 `py -m pip ...`。

### 429 / Rate Limit

请求过快。等待一段时间后重试，不要快速连续按回车。

### 500 / 503

服务端暂时异常或过载。等待后重试。

### APIConnectionError / Timeout / SSL

依次检查：

1. 浏览器能否访问 DeepSeek 开放平台；
2. 终端是否需要代理；
3. 防火墙或公司网络是否拦截；
4. 系统时间是否准确；
5. 换一个网络后是否恢复。

## E. 程序正常，但数字不像预期

### 缓存命中一直是 0

不一定是错误。上下文缓存是 best-effort：

- 第一次请求通常无可复用前缀；
- 缓存建立需要时间；
- 只有完整匹配已经保存的前缀才会命中；
- 缓存可能在数小时到数天内清理；
- 前缀发生变化时可能无法命中。

### 第二轮输入 Token 没有明显增加

检查是否误用了 `/reset`，或第一轮内容过短。尝试让第一轮回答稍长，再进行追问。

### 估算成本与平台账单不同

程序只是估算。先输入 `/prices`，核对：

- 当前模型；
- 官方最新价格；
- 缓存字段是否被 SDK 正确读取；
- 平台是否存在赠送余额或其他结算规则。

### `/reset` 后累计成本没有归零

这是设计行为：

- `/reset` 清空上下文；
- `/clearstats` 清空累计数字。

## F. Key 已经泄露

不要只删除文件或截图。立即在 DeepSeek 平台撤销该 Key，创建新 Key，并检查 Git 历史、截图和录屏是否仍然公开。
