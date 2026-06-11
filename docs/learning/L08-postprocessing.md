# L08: Postprocessing — 输出验证

## 1. 模块在业务流中的位置

Postprocessing 是 VSA Agent 的**输出验证层**，位于 Agent 流程的最后阶段。它负责在最终回复返回给用户之前，对 Agent 的输出进行一系列质量检查。

`
Top Agent DAG
    ↓
agent_node → tool_node → agent_node → ... → finalize_node
                                                 ↓
                                          ┌──────────────┐
                                          │ Postprocessing│  ← 本课
                                          │ Pipeline     │
                                          │  ├─ NonEmpty │
                                          │  ├─ URLCheck │
                                          │  └─ Safety   │
                                          └──────────────┘
                                                 ↓
                                          最终回复给用户
`

**上下游关系：**
- 上游：gents/top_agent.py（finalize_node 之后调用）
- 下游：无（输出验证的最后一步）

---

## 2. 模块设计理念

### 2.1 管道模式（Pipeline Pattern）

Postprocessing 使用**管道模式**，将多个验证器串联执行：

`
输出 → [Validator 1] → [Validator 2] → [Validator 3] → 结果
         ↓ failed          ↓ failed          ↓ failed
      返回失败          返回失败          返回失败
`

- 验证器按顺序执行
- 第一个失败的验证器立即终止管道
- 所有验证器通过才返回成功

### 2.2 验证器策略模式

每个验证器继承 BaseValidator 抽象基类，实现 alidate() 方法：

| 验证器 | 文件 | 验证内容 |
|--------|------|----------|
| **NonEmptyValidator** | alidators/non_empty.py | 输出不为空 |
| **URLValidator** | alidators/url_check.py | URL 格式正确 |
| **SafetyChecklistValidator** | alidators/safety_checklist.py | 包含安全相关关键词 |

### 2.3 设计要点

1. **策略模式（Strategy Pattern）**：BaseValidator 定义验证接口，具体验证器实现不同策略。
2. **短路求值（Short-circuit Evaluation）**：管道在第一个失败时立即停止，避免不必要的验证。
3. **可扩展性**：新增验证器只需继承 BaseValidator 并实现 alidate()，然后加入 ValidationPipeline 的验证器列表。
4. **异常安全**：每个验证器调用被 try/except 包裹，异常时返回失败结果。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **Python bc** | 抽象基类定义 |
| **Pydantic v2** | 验证结果模型 |
| **Python e** | URL 正则匹配 |

---

## 4. 数据模型与接口设计

### 4.1 核心数据模型

`python
class PostprocessingResult(BaseModel):
    """后处理结果"""
    passed: bool          # 是否通过
    feedback: str = ""    # 失败时的反馈信息

class ValidatorResult(BaseModel):
    """验证器结果"""
    name: str             # 验证器名称
    passed: bool          # 是否通过
    issues: list[str] = []  # 问题列表
`

### 4.2 抽象基类 (alidators/base.py)

`python
class BaseValidator(ABC):
    name: str = "base_validator"

    def __init__(self, feedback_template: str = ""):
        self.feedback_template = feedback_template

    @abstractmethod
    async def validate(self, output: str, **kwargs: Any) -> ValidatorResult:
        """对输出执行验证。"""

    def format_feedback(self, issues: list[str]) -> str:
        """将问题列表格式化为反馈字符串。"""
`

### 4.3 验证管道 (pipeline.py)

`python
class ValidationPipeline:
    def __init__(self, validators: list[BaseValidator] | None = None):
        self.validators = validators or []

    async def process(self, output: str) -> PostprocessingResult:
        """顺序执行所有验证器，首个失败即停止。"""
`

### 4.4 内置验证器

`python
class NonEmptyValidator(BaseValidator):
    """验证输出不为空。"""
    name = "non_empty_response_validator"
    async def validate(self, output: str, **kwargs) -> ValidatorResult:
        if not output or not output.strip():
            return ValidatorResult(name=self.name, passed=False, issues=["Response is empty"])
        return ValidatorResult(name=self.name, passed=True)

class URLValidator(BaseValidator):
    """验证输出中的 URL 格式正确。"""
    name = "url_validator"
    URL_PATTERN = re.compile(r"https?://[^\s]+")
    async def validate(self, output: str, **kwargs) -> ValidatorResult:
        urls = self.URL_PATTERN.findall(output)
        invalid = [u for u in urls if not u.startswith(("http://", "https://"))]
        if invalid:
            return ValidatorResult(name=self.name, passed=False, issues=[f"Invalid URLs: {invalid}"])
        return ValidatorResult(name=self.name, passed=True)

class SafetyChecklistValidator(BaseValidator):
    """验证输出包含安全相关关键词。"""
    name = "safety_checklist_validator"
    SAFETY_KEYWORDS = ["hard hat", "safety", "PPE", "violation", "helmet", "red zone", "forklift"]
    async def validate(self, output: str, **kwargs) -> ValidatorResult:
        found = [kw for kw in self.SAFETY_KEYWORDS if kw.lower() in output.lower()]
        if not found:
            return ValidatorResult(name=self.name, passed=False, issues=["No safety keywords found"])
        return ValidatorResult(name=self.name, passed=True)
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/agents/postprocessing/test_pipeline.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestPostprocessingResult | 	est_defaults | 默认值正确 |
| TestValidatorResult | 	est_defaults | 默认值正确 |
| TestNonEmptyValidator | 	est_empty_output_fails | 空输出失败 |
| TestNonEmptyValidator | 	est_non_empty_passes | 非空输出通过 |
| TestURLValidator | 	est_valid_urls_pass | 有效 URL 通过 |
| TestSafetyChecklistValidator | 	est_safety_keywords_pass | 含安全关键词通过 |
| TestSafetyChecklistValidator | 	est_no_keywords_fails | 无安全关键词失败 |
| TestValidationPipeline | 	est_all_validators_pass | 所有验证器通过 |
| TestValidationPipeline | 	est_first_failure_stops | 首个失败即停止 |
| TestValidationPipeline | 	est_empty_validator_list | 空验证器列表通过 |

---

## 6. 动手练习

### 练习 1：理解管道模式

回答以下问题：
1. 如果 NonEmptyValidator 和 SafetyChecklistValidator 都加入管道，执行顺序是什么？
2. 如果第一个验证器失败，第二个还会执行吗？
3. 如何添加一个新的验证器到管道？

### 练习 2：实现自定义验证器

假设需要实现一个 LengthValidator，验证输出长度不超过 2000 字符：
1. 新建文件 alidators/length_check.py
2. 继承 BaseValidator，实现 alidate() 方法
3. 写出完整的代码

### 练习 3：理解验证策略

回答以下问题：
1. SafetyChecklistValidator 的 SAFETY_KEYWORDS 列表包含哪些关键词？
2. 如果输出是 "No safety violations found"，会通过 SafetyChecklistValidator 吗？为什么？
3. URLValidator 使用什么正则表达式匹配 URL？

---

> **下一步**：学习 [L09: API + Embed — 外围层](L09-api-embed.md)
