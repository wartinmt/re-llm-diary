# 配套代码 03：跨启动的本地对话记忆

对应《RE:从零开始的大模型研究日记 03｜关掉终端以后，它为什么不认识我了？》。

本章把只存在于内存中的 `messages` 保存为本地 JSON 文件。程序重新启动后会验证并恢复历史，再把它们作为上下文提交给无状态聊天 API。

## 文件

```text
chapters/03-persistent-memory/
├── main.py
├── memory.py
├── requirements.txt
├── .env.example
├── README.md
├── TROUBLESHOOTING.md
├── LAB_NOTES.md
├── VERIFICATION.md
└── tests/
```

运行后会自动创建 `data/conversation.json`。仓库根目录的 `.gitignore` 应忽略 `.env` 和 `data/`。

## 三层检查

macOS / Linux：

```bash
python3 -m unittest discover -s tests -v
python3 main.py --self-test
python3 main.py --check-config
python3 main.py --check-memory
python3 main.py
```

Windows PowerShell 将 `python3` 替换为 `py`。

- 单元测试：7 项，包括付费回答成功但本地保存失败时仍显示回答；
- `--self-test`：在临时目录验证保存、恢复、损坏保护和删除；
- `--check-config`：读取配置但不发送请求；
- `--check-memory`：验证当前记忆文件；
- 正常运行：与 DeepSeek 对话，并在每轮成功后自动保存。

## 命令

- `/where`：显示记忆文件位置；
- `/history`：显示保存的消息数量；
- `/save`：手动保存；
- `/forget`：输入 `DELETE` 后删除当前记忆；
- `/exit`：保存并退出。

## 可靠性设计

- API 请求失败时，不把失败的用户消息写入记忆；
- 写入时先创建同目录临时文件，再使用原子替换；
- 存档格式不合法时拒绝加载，不悄悄覆盖原文件；
- 记忆文件只保存角色、消息正文、版本和保存时间，不保存 API Key。

## 官方依据

DeepSeek 的聊天 API 是无状态的；要实现多轮对话，调用方需要在每次请求中重新提交此前消息。资料核对日期：2026-07-14。

## 公开仓库

https://github.com/wartinmt/re-llm-diary
