---
comet_change: stabilize-test-contracts
role: technical-design
canonical_spec: openspec
---

# 测试契约稳定化技术设计

## 实现边界

本变更只调整测试契约和 DashScope 实时运行器的无密钥前置条件：

- 不修改 `src/vsa_agent/tools/video_report_gen.py` 的报告语言、区段文案或下载元数据。
- 不改变 `AppConfig.from_yaml()` 在生产中合并 `config.local.yaml` 的行为。
- 不移除现有的条件跳过。

## 报告流程测试

受影响的报告验收测试位于 `tests/acceptance/test_phase6_report_postprocessing_flow.py` 与 `tests/acceptance/test_report_flow.py`。它们将以测试内的小型 Markdown 辅助函数解析非空行和 ATX 标题层级，并断言：

1. 输出包含一个一级标题；
2. 必需内容区段使用二级标题并按生成器输出顺序出现；
3. 传入的来源、查询、摘要、事件描述和时间戳范围仍出现在对应内容区段；
4. 校验失败时存在额外二级区段，且包含每项反馈文本；
5. 多视频报告保留三级事件区段、来源名称和事件描述覆盖。

测试不得比较任何标题字符串，因此生成器将来切换中文、英文或其他本地化文案时，数据契约仍受保护。下载元数据和结构化报告输入继续由现有工具测试覆盖。

## 配置医生测试

`tests/unit/test_config.py::test_config_doctor_cli_reports_missing_key` 启动子进程。该子进程环境除移除 `DASHSCOPE_API_KEY` 外，还将设置 `VSA_LOCAL_CONFIG=""`。这是现有配置模块定义的禁用本地覆盖语义，能让 `config.yaml` 成为测试唯一配置输入，同时不会改变生产加载顺序。

测试继续断言 `config doctor` 返回 `1` 并报告 `DASHSCOPE_API_KEY`。无需改动配置实现。

## DashScope 包装脚本

`scripts/run_live_acceptance_dashscope.sh` 与 `scripts/run_live_top_agent_video_dashscope.sh` 在调用 conda、`config doctor`、`config print` 和 Python 配置读取之前检查 `DASHSCOPE_API_KEY` 是否为空：

```bash
if [[ -z "${DASHSCOPE_API_KEY:-}" ]]; then
  echo "DASHSCOPE_API_KEY is required via environment or ignored config.local.yaml." >&2
  exit 2
fi
```

该检查使用环境变量这一明确的实时运行器输入，不再依赖 Python 在不同 Shell 中解析本地文件的结果。检查通过后，脚本保持现有配置诊断、打印、Key 解析、模型解析、视频路径解析和实际运行命令不变。这样无 Key 路径稳定返回 `2`，携带 Key 时不会掩盖配置错误。

对应单元测试的子进程环境也设置 `VSA_LOCAL_CONFIG=""`，确保测试不会让本地秘密文件绕过无 Key 前置条件。测试保留对 stderr 文案、退出码和未启动 pytest/实时模块的断言。

## 验证策略

1. 先运行两个报告验收文件、`tests/unit/test_config.py` 和 `tests/unit/test_dashscope_live_runner.py`。
2. 使用工作区内的临时目录设置 `TEMP` 与 `TMP`，消除 Windows 默认临时目录权限对结果的影响。
3. 运行全量 `python -m pytest -q`；验收标准是此前九项失败消失，四项跳过仍以条件跳过形式保留。
4. 将全量结果和跳过说明更新到 `docs/DEVELOPMENT_STATUS.md`。

## 风险控制

- 结构化测试只验证层级、顺序与数据，不把当前标题文案重新引入契约。
- 仅对无 Key 的脚本入口提前退出；提供 Key 时仍执行现有的配置诊断和运行路径。
- 修改 Shell 文件时保持 LF 行尾，满足 `.gitattributes` 和现有测试。
