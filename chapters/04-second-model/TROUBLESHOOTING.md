# 配套代码 04：常见报错

## 程序提示“没有找到可用的模型配置”

至少一个 Key 没有填写，或 `.env` 仍保留示例文字。确认 `.env` 与 `main.py` 在同一目录。

## `/models` 只显示一个模型

程序允许单模型运行。这通常说明另一套 Key 尚未填写或被识别为示例占位符。输入 `--check-config` 查看已配置项。

## `/compare` 提示需要两个模型

这是正常保护。先让 `/models` 同时显示 `deepseek` 和 `glm`。

## DeepSeek 成功、GLM 失败

依次检查：

1. `ZAI_API_KEY` 是否来自智谱开放平台；
2. `ZAI_BASE_URL` 是否为 `https://open.bigmodel.cn/api/paas/v4/`；
3. `ZAI_MODEL` 是否为平台当前支持的模型；
4. 账户是否有调用权限和可用额度；
5. 当前网络是否能访问该平台。

## GLM 成功、DeepSeek 失败

检查 DeepSeek Key、余额、模型名和网络。一个提供方失败不会自动证明另一个配置有问题。

## 401 / Authentication Error

对应提供方的 API Key 无效、被撤销或复制不完整。不要把两家的 Key 填反。

## 402 / Insufficient Balance

对应账户没有可用余额。两个平台分别结算。

## 404 / Model Not Found

模型名可能变化。以对应平台当前官方文档为准，不要把 `glm-5.2` 发给 DeepSeek，也不要把 `deepseek-v4-flash` 发给智谱。

## 429 / Rate Limit

请求过快或额度受限。`/compare` 会依次调用两个平台，因此会产生两次独立请求。

## `/compare` 之后 `/history` 没有增加

这是设计行为。比较结果是临时观测，不写入正式记忆。

## 切换模型以后，它能看到之前的对话

也是设计行为。两个模型共用同一份经过验证的本地消息历史。模型可以替换，程序维护的上下文仍然连续。

## Key 已出现在截图或 GitHub

立即到对应平台撤销该 Key 并创建新 Key。只删除截图或文件并不足够。
