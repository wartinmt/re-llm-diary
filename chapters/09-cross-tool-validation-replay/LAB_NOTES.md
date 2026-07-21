# 第 09 章实验记录

## 实验 A：正常跨工具执行

```bash
python3 main.py --demo-success
```

记录文档写入、文档验证、索引登记、组合验证和完成标记的顺序。

## 实验 B：两个成功回执，组合验证失败

```bash
python3 main.py --demo-validation-failure
```

观察索引工具仍会返回成功，但 Runtime 不写 `workflow_completed`。

## 实验 C：第一步之后崩溃

```bash
python3 main.py --demo-resume
```

确认恢复后目录里仍只有一个 Markdown 文件，并出现 `step_receipt_recovered`。

## 实验 D：逆序回滚

```bash
python3 main.py --demo-rollback
```

确认补偿顺序是 `register_index` → `write_document`。

## 实验 E：只读重放

在测试中比较 replay 前后的流水账字节，确认读取事件不会修改文件或重新调用工具。

## 一句话结论

> 跨工具可靠性不是每一步都返回成功，而是 ________________________________________________。
