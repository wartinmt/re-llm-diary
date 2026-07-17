# 配套代码 06：把成本与结果验证纳入路由

对应《RE:从零开始的大模型研究日记 06｜路由器开始算账，也开始怀疑答案》。

第 05 章已经能根据任务形状、历史评分、可靠性和速度自动选模型。本章把两个此前仍然模糊的东西变成可观察数据：调用前的预计成本、调用后由 API `usage` 返回的实际 Token 与成本。随后加入一个受单轮预算约束的第二模型验证步骤。

它不是自动裁判系统。验证器只给出 `PASS`、`REVISE` 或 `UNCERTAIN`，而且只有在策略、复杂度、候选分差与剩余预算允许时才会参与。两个模型仍可能犯相似的错，因此验证结果必须被理解为额外证据，而不是事实证明。

## 文件

```text
chapters/06-cost-verification/
├── main.py
├── providers.py
├── router.py
├── verifier.py
├── costs.py
├── metrics.py
├── memory.py
├── requirements.txt
├── .env.example
├── README.md
├── TROUBLESHOOTING.md
├── LAB_NOTES.md
├── VERIFICATION.md
└── tests/
```

## 最短成功路径

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 -m unittest discover -s tests -v
python3 main.py --self-test
python3 main.py --check-config
python3 main.py --check-memory
python3 main.py --check-router
python3 main.py
```

Windows PowerShell 将 `python3` 替换为 `py`，激活命令使用：

```powershell
.\.venv\Scripts\Activate.ps1
```

先运行离线测试，再编辑 `.env` 填入 Key。`--self-test`、单元测试和所有 `--check-*` 都不会发送 API 请求。

## 关键命令

- `/policy balanced`：能力、速度与成本取中间值；
- `/policy economy`：更积极地压低预计成本；
- `/policy trust`：提高质量、可靠性与验证权重；
- `/verify auto|on|off`：自动判断、总是尝试或关闭第二模型验证；
- `/budget 0.05`：设置本次运行中的单轮人民币预算；
- `/route 问题`：只在本地预览任务类型、候选得分、预计成本和验证计划；
- `/costs`：查看累计 Token、缓存命中率，以及主回答、验证和比较各自的成本；
- `/compare 问题`：不写入正式记忆，但真实调用会计入成本；
- `/good`、`/bad`、`/rate 1-5`：继续为最近一次主回答提供质量反馈。

## 成本是怎样算出来的

调用前，程序用一个透明的字符近似法估算输入 Token，并结合任务类型、复杂度、历史平均输出长度和缓存命中率估算输出。它只服务于路由和预算预览，不用于账单。

调用后，程序读取 API 响应中的 `usage`。能识别提供方直接返回的缓存命中/未命中字段，也能读取 OpenAI 兼容的 `prompt_tokens_details.cached_tokens`。没有缓存细分时，输入全部按未命中计算，避免低估。

`.env` 中所有价格的单位都是“人民币 / 百万 Token”。默认值核对于 2026-07-17，但平台可以随时调整价格。每次长期实验前，都应从官方价格页复核。

## 验证什么时候发生

`VERIFY_MODE=auto` 时，满足以下任一信号才考虑验证：

- `trust` 策略正在处理复杂任务；
- 任务复杂度很高；
- 首选与次选模型得分很接近。

之后还必须存在第二个已配置模型，而且预计验证成本不能超过主回答后的剩余单轮预算。验证器默认不因文风不同而重写，只检查明显的逻辑冲突、遗漏约束和回答不完整。

## 两份本地状态

- `data/conversation.json`：最终展示给用户并成功保存的正式对话；
- `data/router_state.json`：计数、耗时、评分、Token、缓存和成本，不保存问题正文或回答正文。

`/forget` 只删除正式对话。成本实验若要完全重置，应退出程序后先备份，再删除 `router_state.json`。

## 重要边界

- 本地成本是按当前 `.env` 价格对成功响应的 `usage` 计算，不替代平台账单；
- 失败请求可能仍被平台计费，但没有 `usage` 时本地无法准确记录；
- 单轮预算是本地软边界：用于选择和决定是否验证，不能让提供方停止已发出的请求；
- 验证模型可能与主模型共享盲点；
- `REVISE` 只有在验证器给出完整替换答案时才会自动替换；
- `UNCERTAIN` 会保留主答案并附加明确提示；
- API Key 只进入本机 `.env`，路由记录不保存提示词正文。

## 官方资料

- DeepSeek 模型与价格：https://api-docs.deepseek.com/zh-cn/quick_start/pricing
- 智谱模型文档：https://docs.bigmodel.cn/cn/guide/models/text/glm-5.2
- 智谱价格页：https://open.bigmodel.cn/pricing
