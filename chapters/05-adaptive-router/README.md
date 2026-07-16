# 配套代码 05：第一次让程序自己选模型

对应《RE:从零开始的大模型研究日记 05｜我第一次让程序自己选模型》。

本章在第 04 章双模型客户端上增加一个透明路由层。它不会预先规定“某个模型永远负责某类任务”，而是把本地可观测信号保存下来：

- 请求成功或失败；
- 实际响应时间；
- 用户主动输入的 1-5 分评分；
- 当前问题被启发式分类为 general、analysis、code 或 writing。

路由状态不会保存完整提示词或模型回答。

## 文件

```text
chapters/05-adaptive-router/
├── main.py
├── providers.py
├── memory.py
├── router.py
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
python3 main.py --self-test
python3 main.py --check-config
python3 main.py --check-router
python3 main.py
```

Windows PowerShell 将 `python3` 换成 `py`。

- `--self-test`：不联网，验证分类、评分、选择、保存和隐私边界；
- `--check-config`：读取 `.env`，不发送 API 请求；
- `--check-router`：验证 `data/router_state.json`；
- 正常运行：开始真实对话与路由观测。

## 主要命令

- `/auto`：启用自动路由；
- `/use deepseek`、`/use glm`：进入手动模式；
- `/policy balanced|fast|quality`：调整目标权重；
- `/route 问题`：本地预览，不调用 API；
- `/why`：解释上一次路由；
- `/router-stats`：查看成功率、响应时间与评分；
- `/rate 1-5`：为最近一次普通回答评分；
- `/router-reset`：清空路由观测，不删除对话；
- `/compare 问题`：用相同上下文比较模型，不写入正式对话记忆。

## 这不是“最优路由器”

本章的任务分类仍然是透明启发式规则，用户评分也可能有偏差。它的价值是建立一个可以观察、解释、修改和回滚的基线，而不是宣称已经知道哪个模型真正更强。

## 本地数据

运行后会创建：

- `data/conversation.json`：对话正文；
- `data/router_state.json`：数字统计、任务分类和选择解释。

仓库根目录应忽略 `.env`、`.venv/` 和 `**/data/`。

## 验证

离线验证范围与已知边界见 [VERIFICATION.md](VERIFICATION.md)。

## 许可

本章代码沿用仓库根目录的 MIT License。
