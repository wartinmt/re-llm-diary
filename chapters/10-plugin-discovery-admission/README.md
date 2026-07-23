# 配套代码 10：陌生工具的发现、拒绝与准入

对应《RE:从零开始的大模型研究日记 10｜我让 Runtime 接入一个陌生工具，它先拒绝了一次》。

第 09 章已经能验证跨工具组合结果并逆序回滚，但工具本身仍由程序预先知道。本章把“工具接入”拆成可观察的离线流程：只读发现、manifest 校验、AST 静态检查、隔离 probe / preview、显式准入、源码指纹失效、单步澄清和幂等执行。

## 运行要求

- Python 3.10 或更高版本；
- macOS、Linux 或 Windows PowerShell；
- 完全使用 Python 标准库；
- 不需要 API Key，也不会访问网络。

## 文件

```text
chapters/10-plugin-discovery-admission/
├── main.py
├── models.py
├── manifest.py
├── scanner.py
├── plugin_runner.py
├── admission.py
├── registry.py
├── receipts.py
├── runtime.py
├── plugins/
│   ├── safe_lookup/
│   ├── local_note/
│   ├── bad_probe/
│   └── manifest_mismatch/
├── tests/
├── requirements.txt
├── .env.example
├── README.md
├── TROUBLESHOOTING.md
├── LAB_NOTES.md
└── VERIFICATION.md
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
$env:PYTHONUTF8="1"
py -m unittest discover -s tests -v
py main.py --self-test
```

预期看到 76 项测试通过。全部命令离线运行。

## 四个离线演示

```bash
python3 main.py --demo-discovery
python3 main.py --demo-admission
python3 main.py --demo-clarification
python3 main.py --demo-stale
```

Windows 将 `python3` 换成 `py`。

## 三阶段接入

1. **发现**：只读取 `plugin.json` 和入口源码，不导入插件；
2. **检查**：核对 manifest、类与方法，拒绝明显危险导入和调用；
3. **准入**：在临时目录、独立进程中运行 `probe` 与 `preview`，检测是否留下文件副作用。

只读工具通过检查后可准入；会产生副作用的工具还需要显式 `CONFIRM`。准入记录绑定 manifest 与入口源码 SHA-256 指纹。执行子进程启动前会再次计算指纹，任一文件变化都会拒绝旧报告并要求重新检查和准入。

## 这不是安全沙箱

AST 检查、临时目录和子进程只能发现本章演示中的一部分风险，不能阻止精心编写的恶意插件越权访问系统。本章目标是建立透明、可验证、默认拒绝的接入基线，不是宣称可以安全运行任意不可信代码。

## 单步澄清

插件通过 `required_inputs` 声明最小输入。Runtime 每次只返回第一个缺失字段的问题。示例本地笔记先问标题，再问目录，不会一次抛出配置表。

## 幂等执行

执行前根据插件名、准入指纹与全部已声明输入生成稳定计划键；未声明输入会被拒绝。相同计划再次提交时复用持久回执，不重复写文件。工具源码变化后，旧准入失效，执行会被拒绝，直到重新检查和准入。
