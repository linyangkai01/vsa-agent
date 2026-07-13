## 1. 依赖与入口清单

- [x] 1.1 以当前工作树为基线，重新审计 14 个脚本及新增入口的调用者、平台、职责和验证命令；只记录、不修改生产录制视频运行栈的重叠文件。
- [x] 1.2 将脚本入口清单写入当前运行文档，标明保留、合并候选和删除候选。
- [x] 1.3 为共享 DashScope 前置行为添加失败优先的 wrapper 回归测试。

## 2. 合并 DashScope 前置逻辑

- [ ] 2.1 新增单一 shell 公共 helper，集中仓库定位、Conda、配置、API key 和 runtime config 解析。
- [ ] 2.2 将 `run_live_acceptance_dashscope.sh` 迁移为保留原命令和 evaluator 行为的薄 wrapper。
- [ ] 2.3 将 `run_live_top_agent_video_dashscope.sh` 迁移为保留视频参数、query 和 mode 行为的薄 wrapper。

## 3. 清理与文档迁移

- [ ] 3.1 复核 ES、UI、smoke、安装和服务器同步脚本的职责，保留必要的双平台入口。
- [ ] 3.2 对真正冗余的 wrapper 迁移全部文档、测试、包命令和脚本调用者，并再次证明引用数为零后删除。
- [ ] 3.3 更新 `package.json`、运行文档和 `docs/DEVELOPMENT_STATUS.md`，只暴露受支持入口。

## 4. 验证

- [ ] 4.1 对所有 Bash 脚本运行语法检查，对 PowerShell 脚本运行解析检查。
- [ ] 4.2 运行脚本相关单元测试和全量 `pytest -q`。
- [ ] 4.3 对服务器运行入口执行同步前检查和批准的服务器侧 smoke/validation，记录结果与回滚命令。
