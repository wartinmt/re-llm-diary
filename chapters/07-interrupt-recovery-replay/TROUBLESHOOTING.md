# 配套代码 07：常见报错

## `任务流水账末尾存在未完成事件`

程序可能恰好在写一行 JSON 时退出。先备份整个 `data/`，再运行：

```bash
python3 main.py --repair-journal
```

它只会移除最后一个没有换行的残片，并生成 `.partial.bak` 备份。若错误发生在文件中间，程序会拒绝修复。

## `哈希链断裂` 或 `内容哈希不匹配`

文件被修改、事件缺失或顺序发生变化。不要继续运行真实请求，也不要手工把报错行删掉。保留原文件，复制一份进行分析；需要继续实验时使用新的流水账路径。

## 状态是 `remote_unknown`

请求已经发出，但本地没有可信响应。不要反复重启期待程序自动继续。先到提供方控制台检查用量和日志；确认愿意承担重复调用后再输入：

```text
/retry TASK_ID CONFIRM
```

新调用会进入 attempt 2，旧 attempt 仍保留。

## 启动后自动补进了一轮对话

这是 `local_finalize` 或 `local_commit` 的本地恢复：回答在崩溃前已经完整写入流水账，只是正式记忆还没提交。程序没有再次调用 API。使用 `/replay TASK_ID` 查看事件。

## `/recover` 提示会产生 API 调用

任务处于 `safe_to_send`，说明只有 prompt 落盘，请求还没有发出。`/recover` 只允许纯本地动作，因此拒绝。直接重新输入问题，或明确处理该任务。

## `/retry` 提示必须输入 `CONFIRM`

这是有意的摩擦。`yes`、`Y` 或回车都不够，因为新 attempt 可能重复付费或副作用。

## `/replay` 找不到任务

先运行 `/tasks`，复制完整的 12 位任务 ID。流水账路径可用 `/where` 查看。

## Windows 中文输出报编码错误

项目工作流已设置 `PYTHONUTF8=1`。本地 PowerShell 可先执行：

```powershell
$env:PYTHONUTF8="1"
```

再重新运行测试。

## `ModuleNotFoundError`

确认位于 `chapters/07-interrupt-recovery-replay`，已经激活虚拟环境，并安装本章 `requirements.txt`。

## API Key 或流水账出现在截图中

API Key 泄露后立即撤销。流水账可能包含完整问题和回答；停止分享原文件，必要时删除公开附件，并检查是否包含个人或项目敏感信息。
