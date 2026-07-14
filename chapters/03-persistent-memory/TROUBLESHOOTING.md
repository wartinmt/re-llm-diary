# 配套代码 03：常见报错

## 找不到 `main.py`

当前终端目录不对。`ls -la`（macOS）或 `Get-ChildItem -Force`（Windows）后，必须直接看到 `main.py` 和 `memory.py`。

## `No module named openai` 或 `dotenv`

激活 `.venv` 后重新安装 `requirements.txt`。

## `没有找到可用的 DEEPSEEK_API_KEY`

确认 `.env.example` 已复制为 `.env`，且示例文字已经被自己的 Key 替换。不要把 `.env` 上传到公开仓库。

## `无法读取记忆文件` 或 JSON 格式错误

程序不会覆盖损坏文件。先输入 `/where` 或查看 `.env` 中的路径，将 `conversation.json` 改名备份，再重新运行。不要在不了解内容时直接删除唯一副本。

## `不支持的记忆格式版本`

记忆文件来自其他版本。先备份，再根据该版本的迁移说明处理；本章不会自动猜测并覆盖未知格式。

## `Permission denied` 或保存失败

确认本章目录和 `data` 目录可写，磁盘未满，也没有被同步软件锁定。请求成功但保存失败时，本章不会把这一轮加入当前内存，避免“屏幕上有、磁盘里没有”的状态分叉。

## `/forget` 没有删除

必须准确输入大写 `DELETE`。其他输入都会取消操作。

## 重启后模型仍然不知道旧信息

先运行 `--check-memory`，确认消息数量大于 0；再用 `/where` 检查是否读取了预期文件。也可能是你从另一个章节目录运行，导致相对路径基准不同。

## 真实 Key 已经泄露

立即在 DeepSeek 平台撤销并重新创建。仅删除截图或 GitHub 文件不足以恢复安全。
