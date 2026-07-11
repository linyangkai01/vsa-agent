## ADDED Requirements

### Requirement: 缺失密钥诊断使用隔离配置
验证缺失 DashScope API Key 诊断的测试 SHALL 在相关环境变量或开发者本地配置文件均不提供 API Key 的条件下运行。

#### Scenario: 配置医生检测到缺失密钥
- **WHEN** 在不含密钥的隔离配置上下文中，以必需 DashScope Key 调用诊断命令
- **THEN** 命令报告缺失密钥并以状态码 `1` 退出

### Requirement: DashScope 包装脚本保留缺失密钥退出契约
DashScope 运行器包装脚本 SHALL 在可选 Shell 专属配置解析阻止缺失密钥路径执行前，检测到必需 API Key 缺失。

#### Scenario: 包装脚本无密钥运行
- **WHEN** 在隔离配置上下文中调用不含 API Key 的 DashScope 包装脚本
- **THEN** 脚本报告缺失密钥状态并以状态码 `2` 退出

#### Scenario: 包装脚本携带密钥运行
- **WHEN** 使用 API Key 调用 DashScope 包装脚本
- **THEN** 脚本继续既有配置解析和运行时验证行为
