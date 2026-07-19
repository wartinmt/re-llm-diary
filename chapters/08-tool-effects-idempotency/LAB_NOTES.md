# 第 08 章实验记录

## 实验 A：同一个动作只发生一次

```bash
python3 main.py --demo-idempotency
```

记录：

| 项目 | 结果 |
|---|---|
| 第一次是否 reused | |
| 第二次是否 reused | |
| 两次回执是否相同 | |
| 实际文件数量 | |

## 实验 B：工具完成，Runtime 来不及记账

```bash
python3 main.py --demo-receipt-recovery
```

观察：

1. 工具先创建文件并保存自己的持久回执；
2. Runtime 模拟中断；
3. 新进程按原幂等键查询工具；
4. 找回回执后只做本地收尾；
5. 文件数量仍是 1。

## 实验 C：黑盒副作用

```bash
python3 main.py --demo-unknown
```

回答：为什么终端已经显示错误，Runtime 仍然不能断言“动作失败”？

____________________________________________________________________

## 实验 D：补偿不是删除历史

```bash
python3 main.py --demo-compensation
```

记录原动作与补偿动作的：

| 项目 | 原动作 | 补偿动作 |
|---|---|---|
| 幂等键 | | |
| receipt_id | | |
| outcome | | |
| effect_ref | | |

## 实验 E：只读重放

在交互模式中创建一个动作，再执行：

```text
/actions
/replay ACTION_ID
/receipts
```

比较前后 `data/action_journal.jsonl` 的文件哈希，确认 `/replay` 没有写入新事件。

## 一句话结论

> 幂等不是“失败后再试一次”，而是 ________________________________________________。
