# 配套代码 08：工具副作用、幂等与补偿

对应《RE:从零开始的大模型研究日记 08｜AI 说两遍没关系，工具做两遍就可能出事》。

第 07 章解决的是“程序中断后，怎样知道任务做到哪里”。但当 Runtime 开始调用会改变现实的工具，仅仅恢复任务状态还不够：重复生成一段回答通常只是有点啰嗦，重复发消息、创建订单、写文件或改代码却可能产生第二次副作用。

本章把模型调用暂时放到一边，使用两个完全本地的模拟工具，单独观察动作安全：

- 可查询、可补偿的本地笔记工具；
- 无法按幂等键查询结果的黑盒计数器。

所有演示只操作本章 `data/`，不会联网，也不会调用真实 API 或真实外部服务。

## 运行要求

- Python 3.10 或更高版本；
- macOS、Linux 或 Windows PowerShell；
- 不需要 API Key；
- 所有测试和演示均离线运行。

## 文件

```text
chapters/08-tool-effects-idempotency/
├── main.py
├── models.py
├── journal.py
├── receipts.py
├── tools.py
├── actions.py
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
python3 main.py --demo-idempotency
python3 main.py --demo-receipt-recovery
python3 main.py --demo-unknown
python3 main.py --demo-compensation
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
py main.py --demo-idempotency
py main.py --demo-receipt-recovery
py main.py --demo-unknown
py main.py --demo-compensation
```

预期看到：

```text
Ran 98 tests

OK
离线自检通过：动作流水账、幂等回执、未知结果与补偿均正常。
```

`requirements.txt` 只有说明文字，因为本章仅使用 Python 标准库。

## 三个必须分开的东西

### 1. 动作意图

Runtime 准备让哪个工具做什么。它必须在副作用前落盘。

### 2. 工具回执

工具能够证明某个幂等键已经对应一个具体结果。相同幂等键再次出现时，Runtime 应复用回执，而不是再次执行工具。

### 3. 补偿动作

补偿不是删除原记录，也不是假装动作从未发生。它是一个新的、拥有自己幂等键和回执的动作，例如“删除刚才创建的文件”。

## 本章状态

- `action_planned`：动作意图已经持久化；
- `effect_started`：即将进入工具副作用区；
- `effect_confirmed`：工具回执已写入 Runtime；
- `runtime_interrupted`：工具可能完成，但 Runtime 尚未保存本地回执；
- `effect_reconciled`：通过工具查询接口找回回执，没有重复执行；
- `effect_unknown`：工具无法证明结果，禁止自动重试；
- `compensation_planned` / `compensation_completed`：补偿作为独立动作被记录。

## 关键命令

启动实验台：

```bash
python3 main.py
```

- `/create KEY 标题 | 正文`：创建一份本地笔记；
- `/create-crash KEY 标题 | 正文`：模拟工具完成后 Runtime 中断；
- `/recover KEY`：查询工具回执并本地恢复；
- `/opaque KEY`：模拟无法查询结果的黑盒副作用；
- `/retry OLD NEW CONFIRM`：明确授权黑盒未知动作的新尝试；
- `/compensate OLD NEW CONFIRM`：用新动作补偿已确认副作用；
- `/actions`：查看动作摘要；
- `/replay ACTION_ID`：只读重放动作事件；
- `/receipts`：查看本地回执；
- `/where`：显示文件位置。

## 幂等键不是“随便一个 UUID”

幂等键表达的是“同一个业务动作”。同一个动作重放时必须复用同一个键；用户明确决定进行第二次独立尝试时才创建新键。

同一个键再次出现时，Runtime 还会核对原工具与原 payload。键相同但请求
内容不同不是重放，而是冲突；程序会拒绝，不能把旧回执伪装成新效果。

示例：

```text
message:customer-42:invoice-20260719
```

如果每次重试都生成一个新 UUID，工具只会看到不同动作，幂等保护等于没有。

## 为什么黑盒工具不能自动重试

`opaque_counter` 会先增加计数，再模拟响应丢失。Runtime 能看到失败，却无法按幂等键查询工具，也没有可信回执。

这时唯一诚实的状态是 `effect_unknown`。自动重试可能让计数从 1 变成 2；换一个工具或模型也不会改变这个事实。

## 补偿不是回滚时间

本章的笔记工具可以用一个新动作删除原文件。流水账会同时保留：

- 原创建动作及其成功回执；
- 补偿动作及其补偿回执；
- 两者之间的父子关系。

所以最终状态可以恢复，历史却没有被抹去。

## 检查本地状态

```bash
python3 main.py --check-actions
python3 main.py --check-receipts
```

若动作流水账只有末尾半行 JSON，可在先备份 `data/` 后执行：

```bash
python3 main.py --repair-actions
```

它只修复末尾残片，不会自动删除中间损坏事件。

## 安全边界

- 所有工具只写入本章 `data/`；
- 相同幂等键已有 Runtime 回执时，不再次调用工具；
- 工具已完成但 Runtime 中断时，优先查询工具回执；
- 无查询能力且结果未知时，不自动重试；
- 人工重试必须输入 `CONFIRM` 并使用新幂等键；
- 补偿必须输入 `CONFIRM`，并作为新动作保存；
- 动作流水账使用事件序号和 SHA-256 哈希链检查损坏；
- `.env`、`data/`、回执和工具状态都不应提交到 GitHub。
