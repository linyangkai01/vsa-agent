## ADDED Requirements

### Requirement: 脚本入口可追踪
仓库 SHALL 为每个受控运行脚本记录其职责、调用者、目标平台和验证方式。

#### Scenario: 审查脚本清单
- **WHEN** 开发者检查 `scripts/` 中任一入口
- **THEN** 清单 MUST 能定位该入口的调用依据和验证命令

### Requirement: DashScope 前置逻辑共享
DashScope evaluator 与 TopAgent 视频验收入口 SHALL 复用同一套仓库、Conda、配置和密钥校验逻辑。

#### Scenario: 启动任一 DashScope 验收
- **WHEN** 用户运行现有任一 DashScope 验收命令
- **THEN** 系统 MUST 通过共享前置逻辑解析配置，并继续执行该入口原有的目标流程

### Requirement: 平台入口保持
脚本整理 MUST 保留承担不同平台职责的 Windows 和 Linux 运行栈入口。

#### Scenario: 验证双平台入口
- **WHEN** 运行栈脚本完成整理
- **THEN** PowerShell 与 Bash 入口 MUST 保留其现有参数和生命周期职责

### Requirement: 删除需要引用迁移证据
脚本 MUST 仅在所有调用者完成迁移且全仓引用数归零后删除。

#### Scenario: 删除候选脚本
- **WHEN** 某脚本被标记为冗余
- **THEN** 实现 MUST 更新文档、测试、包命令和脚本调用者，并证明删除后不存在悬空引用
