# 配套代码 07：任务中断、恢复与重放

对应《RE:从零开始的大模型研究日记 07｜程序崩了以后，AI 不该假装什么都没发生》。

第 06 章已经能选择模型、计算成本并进行轻量验证，但一次完整任务仍像一段没有存档点的长动作：请求发出后进程退出，程序很难判断“还没开始”“答案已经回来”还是“服务器可能成功、本地却没收到”。本章新增一份追加式任务流水账，把关键阶段在副作用发生前后分别落盘。

## 运行要求

- Python 3.10 或更高版本；
- macOS、Linux 或 Windows PowerShell；
- 离线测试和恢复演示不需要 API Key；
- 真实对话至少需要一把 DeepSeek 或智谱 API Key。

## 文件

```text
chapters/07-interrupt-recovery-replay/
├── main.py
├── journal.py
├── recovery.py
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

### macOS / Linux

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 -m unittest discover -s tests -v
python3 main.py --self-test
python3 main.py --demo-recovery
python3 main.py --check-journal
```

### Windows PowerShell

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
py -m unittest discover -s tests -v
py main.py --self-test
py main.py --demo-recovery
py main.py --check-journal
```

预期看到 50 项测试通过。上述命令不会联网，也不会调用模型。之后再填写 `.env` 中的真实 Key，并运行 `python3 main.py --check-config` 和 `python3 main.py`。

## 流水账记录什么

`data/task_journal.jsonl` 是追加式 JSON Lines 文件。每个事件包含：

- 全局递增 `seq`；
- `task_id` 与 `attempt`；
- 阶段名称和必要载荷；
- 上一事件哈希；
- 当前事件 SHA-256。

完整 prompt 和回答会保存在本机流水账中，以便无 API 恢复。它比 `router_state.json` 更敏感，不要上传 `data/`，也不要把它贴进公开报错。

## 恢复状态

- `safe_to_send`：还没有请求发送记录；继续会产生一次新 API 调用，因此等待用户主动操作；
- `local_finalize`：完整主回答已经落盘，可跳过可选验证并本地收尾；
- `local_commit`：最终答案已落盘，只需写入正式记忆；
- `finish_only`：正式记忆已保存，只缺完成标记；
- `remote_unknown`：请求已经发出但没有可信回执，禁止自动重试；
- `complete`：任务已经完成。

程序启动时只自动处理 `local_finalize`、`local_commit` 和 `finish_only`。这些动作不联网。`remote_unknown` 必须使用 `/retry TASK_ID CONFIRM` 明确创建新的 attempt；旧 attempt 保留，不会被改写。

## 关键命令

- `/tasks`：列出任务与恢复状态；
- `/task ID` 或 `/replay ID`：按事件顺序只读重放；
- `/recover ID`：执行不调用 API 的本地恢复；
- `/retry ID CONFIRM`：在远端结果未知时明确授权新 attempt；
- `/where`：显示正式记忆、路由状态和任务流水账位置；
- 第 06 章的 `/policy`、`/verify`、`/budget`、`/route`、`/costs` 等命令仍然保留。

## 为什么不能自动重试

网络错误只说明本地没有拿到可靠结果，并不能证明服务器没有完成请求。自动切换模型或重发可能产生第二笔费用；如果未来任务包含发邮件、创建订单或修改代码，还可能重复副作用。本章选择把“不知道”保存下来，而不是用一次看似顺滑的重试掩盖它。

## 哈希链能证明什么

哈希链能发现事件被删除、改写、插入或乱序，但它不是数字签名：能修改文件的人也可能重算整条链。本章用它发现意外损坏和普通篡改，不把它宣传成不可伪造审计系统。

## 安全边界

- 在 `request_sent` 事件成功落盘前，不发送 API 请求；
- 主请求结果未知时，不自动 fallback；
- 已落盘的完整回答恢复时不再次调用模型；
- 只有末尾未完成 JSON 片段允许 `--repair-journal` 截断，且先保留备份；
- 中间事件损坏、哈希不匹配或 seq 断裂一律拒绝自动修复；
- `/replay` 只读，不修改文件、不发送 API；
- 流水账包含正文，必须留在本机 `data/`。
