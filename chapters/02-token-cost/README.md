# 配套代码 02：Token、上下文与调用成本

对应《RE:从零开始的大模型研究日记 02｜第二句话，为什么比第一句更贵？》。

本章程序在连续对话的基础上增加了一块用量仪表盘。每轮回答后会显示：

- 输入 Token；
- 缓存命中和缓存未命中的输入 Token；
- 输出 Token；
- 本轮估算成本；
- 本次程序运行期间的累计用量。

成本来自 API 返回的实际 Token 数与 `.env` 中的价格，仅供实验观察，不等同于平台最终账单。

## 文件

```text
chapters/02-token-cost/
├── main.py
├── requirements.txt
├── .env.example
├── README.md
├── TROUBLESHOOTING.md
└── LAB_NOTES.md
```

## 第一次运行前

先阅读随本章发布的 PDF。它包含 macOS 与 Windows 两套完整路径、每一步正常现象、实验记录表、理解检查和答案。

## 三层检查

安装依赖后，建议按顺序运行：

```bash
python3 main.py --self-test
python3 main.py --check-config
python3 main.py
```

Windows PowerShell 将 `python3` 换成 `py`。

- `--self-test`：不联网、不需要 API Key、不产生费用；
- `--check-config`：读取 `.env`，但不发送 API 请求；
- 正常运行：开始真实对话并产生少量 API 用量。

## 命令

- `/stats`：查看累计 Token 与估算成本；
- `/prices`：查看本地估算价格；
- `/reset`：清空对话上下文，保留累计统计；
- `/clearstats`：清空累计统计，保留当前上下文；
- `/help`：查看命令；
- `/exit`：退出程序。

## 价格版本

`.env.example` 中预填的是 2026-07-13 官方页面列出的 `deepseek-v4-flash` 美元价格：

- 缓存命中输入：0.0028 美元 / 100 万 Token；
- 缓存未命中输入：0.14 美元 / 100 万 Token；
- 输出：0.28 美元 / 100 万 Token。

价格可能变化。正式运行前核对：

https://api-docs.deepseek.com/quick_start/pricing/

## 官方资料

- 多轮对话与无状态接口：https://api-docs.deepseek.com/guides/multi_round_chat/
- Token：https://api-docs.deepseek.com/quick_start/token_usage/
- 上下文缓存：https://api-docs.deepseek.com/guides/kv_cache/
- API 字段：https://api-docs.deepseek.com/api/create-chat-completion/
- 错误代码：https://api-docs.deepseek.com/quick_start/error_codes/

## 密钥安全

真实 API Key 只能放在本机 `.env`。不要写入源码，不要上传 `.env`，也不要让 Key 出现在截图、录屏或终端分享中。

## 许可

本章代码沿用仓库根目录的 MIT License。
