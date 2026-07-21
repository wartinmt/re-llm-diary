# 配套代码 09：验证、回滚与跨工具重放

对应《RE:从零开始的大模型研究日记 09｜两个工具都成功了，结果还是错的》。

第 08 章让单个工具动作具备稳定幂等键、持久回执和补偿能力。本章继续向前：即使每一步都只执行一次、每个工具都返回成功，组合结果仍可能违反原计划。因此本章把不可变执行计划、现实状态后置验证、逆序补偿和证据驱动重放放进同一个离线示例。

## 运行要求

- Python 3.10 或更高版本；
- macOS、Linux 或 Windows PowerShell；
- 完全使用 Python 标准库；
- 不需要 API Key，也不会访问网络。

## 文件

```text
chapters/09-cross-tool-validation-replay/
├── main.py
├── models.py
├── receipts.py
├── journal.py
├── tools.py
├── validation.py
├── workflow.py
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
python3 -m unittest discover -s tests -v
python3 main.py --self-test
```

### Windows PowerShell

```powershell
py --version
py -m venv .venv
.\.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py -m unittest discover -s tests -v
py main.py --self-test
```

预期看到 58 项测试通过。全部命令离线运行。

## 四个独立演示

```bash
python3 main.py --demo-success
python3 main.py --demo-validation-failure
python3 main.py --demo-resume
python3 main.py --demo-rollback
```

Windows 将 `python3` 换成 `py`。

## 本章的工作流

1. 保存不可变计划：标题、文档路径、正文哈希、步骤依赖和幂等键；
2. 文档工具写入文件并生成持久回执；
3. Runtime 重新读取磁盘内容，验证文件存在且 SHA-256 符合计划；
4. 索引工具登记标题、路径和哈希；
5. Runtime 联合检查索引记录、文件路径、计划哈希和磁盘真实哈希；
6. 只有组合验证通过，才写入 `workflow_completed`；
7. 失败时可按依赖逆序补偿：先移除索引，再删除文档；
8. 中断恢复先查询已有回执，跳过已被证据确认的步骤。

## 成功不等于正确

工具回执证明某个动作确实发生过，但不能证明整个工作流满足约束。本章故意让索引工具登记旧哈希：两个工具都返回成功，Runtime 仍停在 `validation_failed`，不会宣布完成。

## 重放不是重新执行

`replay()` 只读取事件。真正恢复时，Runtime 先读取不可变计划，再核对工具侧回执和现实状态，只执行仍缺少可信证据的步骤。它不会把整段脚本从第一行再跑一遍。

## 安全边界

- 每次副作用前先保存动作意图；
- 同一幂等键不绑定不同效果；
- 完成标记只能出现在组合验证之后；
- 回滚使用新的补偿键和回执，不删除原成功记录；
- 回滚按依赖逆序执行；
- 流水账使用事件序号和 SHA-256 哈希链发现普通损坏；
- 示例工具只操作临时或本地目录，不调用真实邮件、订单或支付服务。
