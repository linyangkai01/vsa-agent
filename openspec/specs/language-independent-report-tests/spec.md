# language-independent-report-tests Specification

## Purpose
TBD - created by archiving change stabilize-test-contracts. Update Purpose after archive.
## Requirements
### Requirement: 报告流程测试与语言无关
报告流程测试 SHALL 通过文档结构和报告负载内容验证生成的 Markdown，且 MUST NOT 要求本地化标题或区段标题文本。

#### Scenario: 报告包含必需的语义内容
- **WHEN** 从来源、问题、摘要和时间线事件生成报告
- **THEN** 流程测试验证一级标题、顺序明确的二级内容区段，以及给定的来源、问题、摘要和事件值，不比较标题语言

#### Scenario: 报告包含校验反馈
- **WHEN** 报告区段包含校验反馈
- **THEN** 流程测试验证额外区段和每条给定反馈内容，不比较区段标签语言

### Requirement: 报告流程测试保留格式覆盖
报告流程测试 SHALL 在保持语言无关的同时，继续验证 Markdown 下载元数据、事件时间戳格式和可选校验反馈包含情况。

#### Scenario: 渲染带时间戳的事件
- **WHEN** 报告包含具有开始和结束时间戳的事件
- **THEN** 流程测试验证时间线内容中的时间范围和事件描述

