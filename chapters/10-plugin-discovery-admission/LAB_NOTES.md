# 第 10 章实验记录

## 实验 A：发现阶段不执行插件

```bash
python3 main.py --demo-discovery
```

记录四个插件的静态结果。确认 `bad_probe` 在这一阶段尚未产生文件，因为发现只读取 manifest 和 AST。

## 实验 B：probe 成功也可能被拒绝

```bash
python3 main.py --demo-admission
```

观察 `bad_probe` 返回成功但仍被拒绝，因为临时目录快照发生变化。

## 实验 C：每轮只补一个信息

```bash
python3 main.py --demo-clarification
```

记录 Runtime 先问标题、再问目录；相同完整计划第二次执行复用原回执，文件数量仍为 1。

## 实验 D：修改源码让授权过期

```bash
python3 main.py --demo-stale
```

观察状态从 `admitted` 变为 `stale`。思考为什么只改一行注释也需要重新准入。

## 实验 E：人工阅读边界

阅读 `scanner.py` 的禁止导入和禁止调用列表，写下至少三种它仍可能漏掉的越权方式。

## 一句话结论

> 开放式工具接入不是扫描到就能运行，而是 ________________________________________________。
