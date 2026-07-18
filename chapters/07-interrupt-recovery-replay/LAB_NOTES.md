# 第 07 章实验记录

## 实验 A：纯离线恢复

```bash
python3 main.py --demo-recovery
```

记录模拟崩溃前后的状态。确认恢复过程没有 API Key、网络请求或费用。

## 实验 B：检查事件与哈希链

启动一次真实对话后输入：

```text
/tasks
/replay TASK_ID
```

记录 `task_created`、`route_selected`、`request_sent`、`response_received`、`final_answer_ready`、`memory_committed` 和 `task_completed` 的顺序。

## 实验 C：制造末尾残片

只在复制出来的测试流水账上进行。向文件末尾追加半行 JSON，然后运行 `--check-journal` 和 `--repair-journal`。确认原始损坏内容被备份，中间事件没有被改写。

## 实验 D：远端状态未知

阅读 `remote_unknown` 的处理路径，并回答：为什么此时“换一个模型继续”也可能是重复调用？

## 实验 E：只读重放

记录 `/replay TASK_ID` 前后的文件哈希，确认命令没有修改流水账、正式记忆或路由状态。

## 一句话结论

> 恢复不是把程序重新启动，而是 ________________________________________________。
