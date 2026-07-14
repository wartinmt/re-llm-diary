# Verification

发布前离线验证：

```bash
python3 -m unittest discover -s tests -v
python3 main.py --self-test
python3 -m py_compile main.py memory.py
```

已验证范围：

- 缺失存档返回空历史；
- 中文 JSON 往返；
- 损坏 JSON 被拒绝且不被覆盖；
- 不支持的角色被拒绝；
- 删除语义；
- 原子保存后不残留临时文件；
- 主程序离线自检；
- Python 语法编译。

边界：没有使用任何真实用户 API Key，因此真实付费 API 请求不在离线验证范围内。接口字段依据 2026-07-14 DeepSeek 官方文档核对。
