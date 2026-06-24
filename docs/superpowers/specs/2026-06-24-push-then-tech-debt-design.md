# Tech Debt Then Push Design

**Date:** 2026-06-24

**Goal**

在当前 `codex/vsa-agent-closure` 分支已经完成本地收口、全量测试通过的前提下，先把 warning 与缓存噪声安全收口，再整理并推送成果。

## Scope

本设计只覆盖两个顺序执行的子项目：

1. 清理非阻塞技术债
2. 推送当前成果分支

不包含新的主功能开发，不重做现有 evaluator / live API 验收设计。

## Current Context

当前状态：

- 当前分支：`codex/vsa-agent-closure`
- 本地已有 3 个整理后的提交
- 全量测试结果基线：`431 passed, 2 skipped, 2 warnings`

两个已知 warning：

1. `fastapi.testclient` 与 `httpx` 的弃用 warning
2. Windows 下 `.pytest_cache` 写入权限 warning

## Non-Goals

- 不继续扩展 evaluator 功能
- 不在推送前再混入新的业务功能修改
- 不把技术债清理和当前成果推送混成同一个逻辑批次

## Approaches

### Approach A: 先推送，再单独清理技术债

先把当前已验证成果推送到远端分支，随后再以独立小范围处理 warning。

优点：

- 当前成果先落地，风险最低
- 技术债修改不会污染已经整理好的功能提交
- 如果技术债处理引出额外依赖或兼容性问题，不会影响本次主成果交付

缺点：

- 后续仍需一次小范围开发循环

### Approach B: 先清理技术债，再推送

继续在当前分支上修改 warning，再统一推送。

优点：

- 推送时仓库更整洁

缺点：

- 会延迟当前成果落地
- 可能把“非阻塞优化”变成新的风险源

### Decision

采用 Approach B。

## Execution Plan At A High Level

### Phase 1: Tech Debt Cleanup

目标：

- 只处理非阻塞 warning / 噪声
- 不引入新的业务行为变化

验证：

- 相关测试重跑通过
- warning 数量下降到 0
- 如无法安全修复，则形成明确停手理由

当前结论：

- `fastapi.testclient` 弃用 warning 已通过改用 `httpx.AsyncClient + ASGITransport` 消除
- `.pytest_cache` / cacheprovider 权限 warning 已通过禁用 `pytest` cacheprovider 消除
- 最新验证结果：`431 passed, 2 skipped`

### Phase 2: Push Current Branch

目标：

- 推送 `codex/vsa-agent-closure` 到 `origin`
- 保留当前本地提交结构，并追加本次文档/收口提交

验证：

- 工作区干净
- 当前分支正确
- 远端推送成功

## Success Criteria

- 非阻塞 warning 与缓存噪声已收口
- 全量测试保持绿色
- 当前成果分支成功推送到远端
