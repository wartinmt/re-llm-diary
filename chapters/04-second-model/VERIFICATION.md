# Verification

资料核对日期：2026-07-15。

## 实际执行环境

- Python：容器中的 Python 3
- OpenAI Python SDK：2.45.0
- python-dotenv：1.2.1（为兼容常见镜像源固定到该版本）

## 实际执行命令

```bash
python3 -m py_compile main.py providers.py memory.py
python3 -m unittest discover -s tests -v
python3 main.py --self-test
```

结果：13 项单元测试全部通过；离线自检通过。

另外实际执行了两组配置测试：

1. 直接复制 `.env.example` 时，程序拒绝把占位文字当成真实 Key；
2. 使用两枚假的测试 Key 运行 `--check-config` 时，程序正确列出两个模型，输出中没有泄露 Key 的任何字符，也没有发送网络请求。

## 已验证范围

- 中文记忆保存、恢复、删除和损坏保护；
- 示例 Key 不被视为有效配置；
- 同时加载 DeepSeek 与 GLM 官方默认配置；
- `ProviderConfig` 的 `repr` 不泄露 API Key；
- 默认模型安全回退；
- 构造请求时不修改原历史；
- `/compare` 核心逻辑不污染正式记忆；
- 一个提供方失败时，另一个结果仍能保留；
- 主程序离线自检；
- Python 语法编译。

## 官方文档核对

- 智谱官方 OpenAI 兼容文档说明：OpenAI SDK 版本不低于 1.0.0；通过修改 API Key 和 Base URL 可以使用兼容接口；官方示例模型为 `glm-5.2`，Base URL 为 `https://open.bigmodel.cn/api/paas/v4/`；
- DeepSeek Create Chat Completion 官方文档：本章沿用 `https://api.deepseek.com` 与 `deepseek-v4-flash`。

## 部署脚本验证

部署脚本还会在用户本地仓库中重新：

- 在临时隔离环境中安装依赖；
- 安装固定依赖；
- 执行语法检查、13 项单元测试与离线自检；
- 更新首页、路线图、更新记录和参考资料；
- 提交、推送并创建 `v0.0.4` 标签。

## 未声称完成的部分

没有读取任何真实用户 API Key，也没有代表用户执行付费 API 冒烟请求。真实账户权限、余额、地区网络、内容审核和平台临时状态不在离线验证范围内。
