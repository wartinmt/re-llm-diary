# 第 08 章验证报告

## 状态

Verified Offline - 已完成代码、文档、教材和部署包验证；未调用真实模型或外部工具。

## 环境

- Python：3.11（交付环境）；
- 最低支持：Python 3.10；
- 第三方依赖：无；
- 资料与代码核对日期：2026-07-19。

## 已验证

- Python 语法编译；
- 88 项单元测试；
- 同一幂等键只产生一次本地文件副作用；
- 重复动作复用相同 Runtime 回执；
- 工具完成、Runtime 中断后的持久回执恢复；
- 恢复过程不重复执行工具；
- 无查询能力的黑盒工具进入 `effect_unknown`；
- `effect_unknown` 禁止同键自动重试；
- 人工重试必须输入 `CONFIRM` 并使用新幂等键；
- 补偿必须作为新的动作和回执保存；
- 原成功回执在补偿后继续保留；
- 不支持补偿的工具明确拒绝；
- 动作流水账序号、前序哈希和内容哈希校验；
- 末尾半行 JSON 的备份修复；
- 中间损坏、序号错误和哈希篡改拒绝加载；
- Runtime 回执存储原子写入与冲突检测；
- macOS / Linux / Windows PowerShell 命令；
- GitHub Actions 覆盖 Ubuntu、macOS、Windows 与 Python 3.10、3.13；
- 部署脚本不安装依赖、不运行测试、不调用 API；
- 压缩包不包含 `.env`、`data/`、真实 Key、缓存或运行产物。

## 离线命令

```bash
python3 -m py_compile main.py models.py journal.py receipts.py tools.py actions.py
python3 -m unittest discover -s tests -v
python3 main.py --self-test
python3 main.py --demo-idempotency
python3 main.py --demo-receipt-recovery
python3 main.py --demo-unknown
python3 main.py --demo-compensation
python3 main.py --check-actions
python3 main.py --check-receipts
```

## 实际摘要

```text
Ran 88 tests

OK
离线自检通过：动作流水账、幂等回执、未知结果与补偿均正常。
这一步没有访问网络，没有调用模型，也没有操作真实外部服务。
```

## 未验证与边界

- 没有连接真实邮件、支付、代码托管或订单系统；
- 本地笔记工具只是可查询、可补偿工具的最小模型；
- 黑盒工具的 `effect_unknown` 无法由 Runtime 单独消除；
- SHA-256 哈希链可发现普通损坏和改写，但不是数字签名；
- 补偿不等于时间回滚，也不能保证所有现实影响都可撤销；
- 不同平台对幂等键、回执保留期和查询接口的支持需要逐个核对。
