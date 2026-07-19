# 配套代码 08：常见报错

## `idempotency_key must be 3-128 characters`

幂等键只能使用字母、数字、点、下划线、冒号和连字符，长度为 3 到 128 个字符。不要使用空格，也不要把完整正文放进键里。

推荐让键表达稳定的业务动作，例如：

```text
note:weekly-report:2026-07-19
```

## 第二次 `/create` 没有覆盖新正文

这是预期行为。相同幂等键代表同一个动作；第一次成功后，第二次只复用原回执，不会重新执行工具，也不会把新载荷偷偷当成另一个动作。

确实要创建第二份笔记时，请使用新的幂等键。

## `/create-crash` 后看到文件已经存在

这正是实验要模拟的状态：工具已经完成副作用，但 Runtime 在保存本地回执前中断。

不要重新输入 `/create`。重新启动程序并执行：

```text
/recover 原来的幂等键
```

程序会查询本地工具的持久回执，并把结果补回 Runtime。

## 状态是 `effect_unknown`

工具已经进入副作用区，但没有返回可信结果，而且该工具不支持按幂等键查询。不要自动重试，也不要用同一个键重跑。

先检查真实工具的控制台、邮件发送记录、订单列表或代码仓库状态。确认愿意承担重复副作用后，才使用新的幂等键并明确授权：

```text
/retry OLD_KEY NEW_KEY CONFIRM
```

## `/retry` 提示必须使用新幂等键

未知结果的旧动作必须保留。新尝试是一个新的现实动作，因此要用新键，并通过 `parent_action_id` 关联旧动作。

## `/compensate` 提示没有持久回执

只有已经确认成功的动作才能安全补偿。没有回执时，Runtime 不知道应撤销哪个具体效果。

若原动作仍是 `runtime_interrupted`，先执行 `/recover KEY`；若是 `effect_unknown`，先人工确认真实状态。

## 工具不支持补偿

不是所有副作用都可逆。删除本地测试文件可以补偿，但一封已读邮件、一次外部通知或一笔已结算支付可能无法真正撤回。

这种情况下应该提供后续修正动作，而不是谎称“已经回滚”。

## `action journal ends with an incomplete line`

程序可能恰好在写入最后一行 JSON 时退出。先复制整个 `data/` 目录，再运行：

```bash
python3 main.py --repair-actions
```

脚本会保留 `.partial.bak` 备份，并只移除末尾没有换行的残片。

## `journal hash chain broken` 或 `content hash mismatch`

流水账中间事件被修改、删除、插入或乱序。不要继续执行真实动作，也不要手工删掉报错行。

保留原文件进行分析；继续实验时使用新的 `data/` 目录。

## Windows 终端中文乱码

先确认使用 Python 3.10 或更高版本。可以在 PowerShell 当前窗口设置：

```powershell
$env:PYTHONUTF8="1"
```

仓库的 GitHub Actions 工作流已经设置 `PYTHONUTF8=1`，覆盖 Windows 3.10 和 3.13。

## `python3` 找不到

macOS / Linux 运行：

```bash
python3 --version
```

Windows 通常使用：

```powershell
py --version
```

如果版本低于 3.10，请先升级 Python。

## 不小心把 `data/` 或 `.env` 加入 Git

立即取消暂存：

```bash
git restore --staged .env data
```

确认仓库根目录 `.gitignore` 包含 `.env` 和 `**/data/`。动作流水账可能包含业务载荷和文件路径，不应公开。
