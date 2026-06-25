# Live API Provider Overrides Design

**Date:** 2026-06-25

## Goal

让 live API 验收测试可以在不修改主业务默认配置的前提下，切换到任意 OpenAI-compatible 提供商进行真实调用验证，例如百炼兼容接口。

## Scope

本设计只覆盖以下内容：

1. 为 `OpenAIModelAdapter` 增加显式运行时覆盖能力
2. 为 live API acceptance 测试增加 provider override 环境变量入口
3. 更新 live API 验证文档

本设计不覆盖：

- 新增全局 provider 配置系统
- 修改 `VLLMModelAdapter`
- 改动主业务默认模型选择逻辑
- 扩展新的 acceptance 测试场景

## Current Context

当前项目已经具备：

- `OpenAIModelAdapter`，从 `config.model.dev` 读取 `model/base_url/api_key`
- `tests/acceptance/test_evaluator_live_api.py`，可在配置 `OPENAI_API_KEY` 时执行真实模型调用
- `docs/testing/live-api-validation.md`，说明了当前 live API 测试的运行方式

当前限制在于：

- live 测试把真实调用路径绑定在默认 dev 配置和 `OPENAI_API_KEY` 语义上
- 如果要接入百炼这类兼容 OpenAI API 的免费模型，需要通过代码改动或配置替换来切换
- 这种切换方式不够局部，也不够适合“只在验收测试里切 provider”

## Design

### 1. Adapter Runtime Overrides

`OpenAIModelAdapter` 增加以下可选初始化参数：

- `model_name: str | None = None`
- `base_url: str | None = None`
- `api_key: str | None = None`

行为规则：

- 若显式传入覆盖值，则优先使用传入值
- 若未传入，则回退到现有 `config.model.dev` 配置
- `api_key=""` 视为未设置，与当前 blank-key 兼容逻辑保持一致

这样可以保持默认业务路径完全不变，同时允许调用方在局部场景下切换 provider。

### 2. Live API Test Provider Selection

在 `tests/acceptance/test_evaluator_live_api.py` 中增加统一 helper，用于解析 live API 测试运行时设置。

新增环境变量：

- `LIVE_API_MODEL`
- `LIVE_API_BASE_URL`
- `LIVE_API_KEY`

选择规则：

1. 优先读取 `LIVE_API_*`
2. 若未提供 `LIVE_API_KEY`，则回退到现有 `OPENAI_API_KEY`
3. 若未提供 `LIVE_API_MODEL` / `LIVE_API_BASE_URL`，则回退到默认 dev 配置

运行判定规则：

- 只要解析后的有效 API key 存在，就允许执行 live API 测试
- 若解析后没有有效 API key，则与当前行为一致，测试 `skip`

这样可以同时支持：

- 继续使用 OpenAI 默认配置
- 仅在 live 测试中切到百炼兼容接口
- 以后切到别的 OpenAI-compatible provider

### 3. Documentation

更新 `docs/testing/live-api-validation.md`：

- 说明 `LIVE_API_*` 环境变量的优先级
- 保留 `OPENAI_API_KEY` 兼容说明
- 增加百炼兼容接口示例命令
- 明确说明 live 测试默认仍为 opt-in

## Approaches Considered

### Approach A: 只在测试文件里硬编码百炼参数

优点：

- 实现最快

缺点：

- 测试与单一 provider 强耦合
- 后续切换到其他兼容接口仍要改代码
- 不利于长期维护

### Approach B: 给 `OpenAIModelAdapter` 增加显式覆盖参数，并在 live 测试中通过环境变量传入

优点：

- 改动范围小
- 主业务默认行为不变
- 兼容所有 OpenAI-compatible provider
- live 测试入口更清晰、可复用

缺点：

- 需要补少量单测

### Approach C: 建立统一的全局 provider override 配置层

优点：

- 最完整、最系统

缺点：

- 明显超出当前“只为 live 验收切 provider”的范围
- 会引入额外配置复杂度

## Decision

采用 Approach B。

## Testing Strategy

### Unit Tests

为 `OpenAIModelAdapter` 增加覆盖参数相关测试，验证：

- 显式 `base_url/api_key/model_name` 优先于配置
- 未显式传参时仍使用现有配置
- blank api key 仍被视为 unset

为 live API 测试 helper 增加行为锁定，验证：

- `LIVE_API_KEY` 优先于 `OPENAI_API_KEY`
- `LIVE_API_*` 缺失时能正确回退
- 无可用 key 时继续 skip

### Acceptance / Verification

1. 先跑相关单测
2. 再跑全量测试，确保默认行为不变
3. 最后在配置百炼免费模型后，单独运行：
   - `tests/acceptance/test_evaluator_live_api.py`

## Success Criteria

- 默认配置路径保持不变
- `LIVE_API_*` 可驱动 live 测试切到百炼兼容接口
- 无 key 时 live 测试仍然 skip
- 全量测试保持绿色

## Risks And Boundaries

- 不假设所有 OpenAI-compatible provider 在响应细节上完全一致，因此只把切换能力限定在 live 验收入口
- 不在本设计中调整 evaluator 阈值；若百炼输出导致 live 测试断言波动，再单独分析是否属于真实质量差异
- 不扩展到主业务运行时 provider 切换，避免把验收需求演变成全局配置重构
