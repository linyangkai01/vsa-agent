# 验证报告：stabilize-test-contracts

日期：2026-07-11

## 总览

| 维度 | 结果 |
| --- | --- |
| 完整性 | 7/7 OpenSpec 任务完成，4/4 需求已实现 |
| 正确性 | 6/6 规范场景由实现与自动化测试覆盖 |
| 一致性 | 符合设计：不修改报告生成器或生产本地配置加载行为 |

## 完整性

- `language-independent-report-tests`：
  - `tests/acceptance/test_report_flow.py` 和 `tests/acceptance/test_phase6_report_postprocessing_flow.py` 断言标题层级、来源、查询、独立摘要、事件描述、时间戳和校验反馈，而不比较标题文案。
  - 多视频流程验证顶层固定区段层级、两个三级事件区段及两个来源的数据内容。
- `isolated-runtime-config-validation`：
  - `tests/unit/test_config.py` 在临时目录创建带本地 Key 的 `config.local.yaml`，再以 `VSA_LOCAL_CONFIG=""` 证明 `config doctor` 忽略该覆盖并返回 `1`。
  - 两个 DashScope 运行器在 `config doctor` 前检查 `DASHSCOPE_API_KEY` 并以 `2` 退出；运行器测试验证实际无 Key 退出路径、Shell 条件跳过和有 Key 时守卫后的既有解析顺序。

## 正确性

| 场景 | 证据 |
| --- | --- |
| 单视频报告包含语义内容 | 报告验收测试验证一级/二级结构、来源、查询、独立摘要、事件和时间戳 |
| 报告包含校验反馈 | 后处理失败流程验证额外二级区段和每条反馈 |
| 带时间戳事件被渲染 | 单视频流程验证时间范围和事件描述 |
| 配置医生检测缺失 Key | 临时本地配置覆盖被禁用后，CLI 返回 `1` 并输出 `DASHSCOPE_API_KEY` |
| 运行器无 Key | 两个 Bash 子进程返回 `2`，且不进入 pytest/实时模块 |
| 运行器携带 Key | 守卫条件只拦截空 Key；测试验证守卫位于既有 `config doctor` 调用之前 |

## 一致性与审查

- 报告工具 `video_report_gen.py` 未修改，因此未定义输出语言契约。
- `src/vsa_agent/config.py` 未修改，因此生产环境的 `config.local.yaml` 合并优先级保持不变。
- 两个 Bash 文件保持 LF 行尾，并通过 `bash -n`。
- 标准独立审查发现单视频摘要与事件描述使用同一夹具值会掩盖摘要回归；已改为不同值并在最终测试前复验。
- 未发现 CRITICAL、WARNING 或未接受的审查项。

## 验证命令

```powershell
$env:TEMP=(Resolve-Path '.tmp\pytest-verify-final').Path
$env:TMP=$env:TEMP
python -m pytest -q
```

结果：`660 passed, 4 skipped, 1 warning in 22.86s`。

四项跳过均保留为条件跳过。唯一警告来自第三方 `starlette.testclient` 对 `httpx` 的弃用提示，与本变更无关。

```powershell
openspec validate stabilize-test-contracts --strict
```

结果：`Change 'stabilize-test-contracts' is valid`。

## 结论

所有验证检查通过，可进入本地分支收尾与归档准备。
