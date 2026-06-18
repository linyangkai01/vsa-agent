# Phase 7A4 输出解析基础设施对齐设计

> 范围：`utils/parser.py`、`utils/markdown_parser.py`、`agents/critic_agent.py`，以及报告链中的最小 markdown 消费接点
> 日期：2026-06-18
> 目标：补齐原版中缺失的通用解析与 Markdown 解析基础设施，并把现有零散的 JSON/Markdown 剥壳逻辑收口到共享工具层。

## 一、背景

到 Phase 7A3 为止，项目已经完成了以下基础设施对齐：

1. A1：prompt / reasoning / async 生命周期
2. A2：VSS 数据模型 / 时间转换 / 选帧
3. A3：retry / model adapter 重试主链

接下来最自然的一段，是把“模型输出如何被二次消费”这件事补成共享能力。

当前仓库里已经存在两类非常典型的解析需求：

1. **JSON 剥壳需求**  
   `critic_agent.py` 里已经有 `_get_json_from_string()`，它负责把 markdown code block 里的 JSON 抽出来再交给 `json.loads()`。

2. **Markdown 结构消费需求**  
   报告链已经稳定地产出 markdown：
   - `video_report_gen.py`
   - `template_report_gen.py`
   - `report_gen.py`
   - `report_agent.py`
   - `multi_report_agent.py`

   这些模块当前主要“生成 markdown”，但还没有统一工具去“按结构消费 markdown”。这会限制后续的二次处理、摘要抽取、结构校验、UI/下载适配。

因此 A4 的目标不是重写报告链，而是先建立一个最小且稳的“输出解析公共层”。

## 二、现状问题

### 1. JSON 提取逻辑散落在业务模块里

`src/vsa_agent/agents/critic_agent.py` 中的 `_get_json_from_string()` 目前承担了最核心的 parser 责任，但它存在几个问题：

- 逻辑位置不对，属于业务模块内联工具
- 只能处理非常窄的 ` ```json ... ``` ` 场景
- 后续如果别的 Agent / Tool 也要提取 JSON，就只能复制

也就是说，仓库已经出现了 parser 需求，但 아직没有公共 parser 模块承接它。

### 2. markdown 当前主要是“最终字符串”，不是“可消费结构”

报告链中的 markdown 现在更多是交付物，而不是结构化中间表示：

- `template_report_gen.py` 只负责拼接
- `report_gen.py` 只负责组合
- `report_agent.py` / `multi_report_agent.py` 只负责透传

这种方式对当前交付没问题，但一旦后续要做：

- 报告摘要二次提取
- 自动校验 section 是否齐全
- markdown 转其他格式
- UI 层基于 markdown section 做分块展示

就会发现缺少统一解析工具。

### 3. A4 不适合一口气做成完整 Markdown AST 系统

虽然 `markdown_parser.py` 理论上可以做得很大，但当前项目阶段并不需要：

- 不需要完整 CommonMark 语法树
- 不需要复杂嵌套列表/表格/引用解析
- 不需要引入外部 markdown parser 重库

因此 A4 必须有意识地控制范围，避免把一个基础设施补齐阶段做成大重构。

## 三、设计目标

Phase 7A4 的目标如下：

1. 提供共享 `parser.py`  
   抽离 JSON/fenced code block 提取逻辑，供 `critic_agent` 等模块统一复用。

2. 提供共享 `markdown_parser.py`  
   只实现当前真实需要的最小结构解析能力：
   - 提取标题
   - 提取 bullet list
   - 按 heading 切分 section

3. 保持现有 markdown 生成接口不变  
   A4 只补“解析与消费能力”，不重写 report 渲染链。

4. 先接入 `critic_agent` 和一个最小 markdown 消费场景  
   用真实调用点验证工具设计，而不是停留在纯工具文件层面。

## 四、候选方案

### 方案 A：最小共享解析层（推荐）

做法：

- 新增 `utils/parser.py`
- 新增 `utils/markdown_parser.py`
- `critic_agent.py` 改用共享 parser
- 报告链只接一个最小消费点，例如对 markdown 做 section 提取或摘要提取验证

优点：

- 风险小
- 与当前仓库结构贴合
- 能快速形成可复用基础设施

缺点：

- 这轮不会马上带来大规模业务重构效果

### 方案 B：直接重构报告链为“结构生成 + markdown 解析再消费”

做法：

- 在报告链多处引入 markdown parser
- 一并调整 report/template/report_agent 的消费路径

优点：

- 统一性更强

缺点：

- 范围明显过大
- 会把 A4 从基础设施补齐推成业务重构

### 方案 C：只做 `parser.py`，`markdown_parser.py` 延后

做法：

- 先仅收口 `_get_json_from_string()`

优点：

- 最保守

缺点：

- A4 范围过窄
- 没有把 markdown 结构消费基础设施真正立起来

## 五、最终选择

本阶段采用 **方案 A：最小共享解析层**。

理由：

- 它最贴近当前真实需求
- 能先把 parser / markdown_parser 两个空缺模块补上
- 不会过早把报告链推入大规模重构
- 后续若进入 A5/A6，可以直接在已有工具层上继续扩展

## 六、模块设计

### 1. `utils/parser.py`

职责：

- 提供面向文本输出的最小通用解析工具

本阶段建议包含的能力：

1. `extract_fenced_block(text, language=None) -> str | None`
   - 提取第一个 fenced code block
   - `language=None` 时接受任意语言
   - 指定语言时只提取对应 fenced block

2. `extract_json_string(text) -> str`
   - 优先提取 ` ```json ` block
   - 其次提取任意 fenced block
   - 最后回退原始文本

3. `parse_json_payload(text) -> Any`
   - 基于 `extract_json_string()` 做 `json.loads()`
   - 让业务模块少写重复样板

注意：

- 本阶段不做 XML、YAML、混合片段解析
- 不做复杂容错修复 JSON

### 2. `utils/markdown_parser.py`

职责：

- 提供轻量级 markdown 结构消费工具

本阶段建议包含的能力：

1. `extract_headings(markdown: str, level: int | None = None) -> list[str]`
2. `extract_bullet_list(markdown: str) -> list[str]`
3. `split_sections(markdown: str, heading_level: int = 2) -> list[MarkdownSection]`

其中 `MarkdownSection` 建议为轻量 dataclass，字段最少包括：

- `title: str`
- `content: str`
- `heading_level: int`

注意：

- 不做完整 markdown AST
- 不特殊解析表格、引用、代码块内部 markdown
- 只针对当前报告输出风格工作

## 七、接入策略

### 1. `critic_agent.py`

接入方式：

- 删除本地 `_get_json_from_string()` 作为核心实现
- 保留兼容名字也可以，但内部改调 `utils.parser.extract_json_string()`

这样做的好处是：

- 对外行为不变
- 单测只需增加“共享 parser 已接管”的验证

### 2. 报告链最小消费点

A4 不重写整个 report 生成链，只选一个最小接点验证 markdown parser。

推荐接点：

- `template_report_gen.py` 或其测试层，引入 `split_sections()` 的消费验证
- 或单独补一个测试型辅助函数，验证仓库当前生成的 markdown 符合 section parser 的预期

目标不是让 parser 深度入侵 report 逻辑，而是验证“当前 markdown 风格是可被新 parser 消费的”。

## 八、错误处理策略

### `parser.py`

- 没有 fenced block 时，回退原文
- `parse_json_payload()` 遇到非法 JSON 时抛出 `json.JSONDecodeError`
- 不静默吞掉解析错误

### `markdown_parser.py`

- 空字符串返回空列表
- 未命中 heading/bullet 时返回空列表
- 不抛出“格式错误”异常，保持消费层宽容

## 九、测试策略

### 1. `tests/unit/utils/test_parser.py`

覆盖：

- 提取 ` ```json ` code block
- 提取任意 fenced block
- 无 fenced block 时回退原文
- `parse_json_payload()` 成功与失败路径

### 2. `tests/unit/utils/test_markdown_parser.py`

覆盖：

- 提取一级/二级标题
- 提取 bullet list
- 按 `##` 分割 section
- 空 markdown / 无 heading 边界

### 3. `tests/unit/agents/test_critic_agent.py`

覆盖：

- `critic_agent` 继续支持 markdown 包裹的 JSON
- 接入共享 parser 后行为不变

### 4. 报告链最小回归

可以选：

- `tests/unit/tools/test_template_report_gen.py`
- 或新增 `tests/unit/utils/test_markdown_parser_report_samples.py`

目标是验证当前仓库实际产出的 markdown 可以被 section parser 正确切分。

## 十、非目标

本阶段不做以下内容：

- 不引入第三方 markdown 解析库
- 不做完整 AST
- 不重构报告链为“先生成结构化 markdown tree”
- 不做复杂 JSON 修复器
- 不把所有历史字符串处理一次性全部收口

## 十一、验收标准

完成标准如下：

1. 新增 `utils/parser.py`
2. 新增 `utils/markdown_parser.py`
3. `critic_agent.py` 使用共享 parser，而不是本地私有逻辑
4. markdown parser 能正确消费当前报告风格的最小样例
5. A4 相关单测全部通过
6. 唯一总计划文档同步记录 A4 状态

