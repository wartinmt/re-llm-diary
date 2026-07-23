# 配套代码 04：接入第二个模型

对应《RE:从零开始的大模型研究日记 04｜我把第二个模型接了进来》。

本章在第 03 章的本地持久记忆基础上，同时接入 DeepSeek 与 GLM。两个提供方共用 OpenAI Python SDK，但分别使用自己的 API Key、基础地址和模型名。

## 文件

```text
chapters/04-second-model/
├── main.py
├── providers.py
├── memory.py
├── requirements.txt
├── .env.example
├── README.md
├── TROUBLESHOOTING.md
├── LAB_NOTES.md
├── VERIFICATION.md
└── tests/
```

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

- 单元测试：14 项；
- `--self-test`：离线验证记忆、模型选择和临时比较；
- `--check-config`：显示已配置模型，但不显示 API Key、不发请求；
- `--check-memory`：验证本地记忆文件；
- 正常运行：手动切换或比较模型。

## 命令

- `/models`：列出已配置模型；
- `/active`：查看当前模型；
- `/use deepseek`：切换到 DeepSeek；
- `/use glm`：切换到 GLM；
- `/compare 问题`：用相同上下文临时比较所有已配置模型；
- `/where`、`/history`、`/save`、`/forget`：管理本地记忆；
- `/exit`：保存并退出。

`/compare` 的回答不会写入正式记忆。普通对话只由当前激活模型回答，并在成功后保存。

## 当前官方配置

资料核对日期：2026-07-15。

- DeepSeek Base URL：`https://api.deepseek.com`
- DeepSeek 模型：`deepseek-v4-flash`
- 智谱 OpenAI 兼容 Base URL：`https://open.bigmodel.cn/api/paas/v4/`
- GLM 模型：`glm-5.2`

智谱官方文档说明，现有 OpenAI SDK 代码只需修改 API Key 与 Base URL 即可调用其模型；某些高级场景仍可能存在接口差异。

## 安全边界

- 真实 Key 只保存在本机 `.env`；
- 配置检查不会显示 Key 内容；
- 记忆文件不会保存 Key；
- 一个模型请求失败，不会写入半轮记忆；
- 临时比较不会污染正式对话。

## 公开仓库

https://github.com/wartinmt/re-llm-diary
