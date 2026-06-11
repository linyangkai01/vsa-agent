# L03: Model Adapter — LLM/VLM 抽象层

## 1. 模块在业务流中的位置

Model Adapter 是 VSA Agent 的**模型调用抽象层**，位于 Agent 编排层和具体模型 API 之间。它为上层提供统一的 LLM/VLM 调用接口，屏蔽不同模型提供商的差异。

`
Agents (top_agent, search_agent, critic_agent)
       ↓ 调用
┌─────────────────────────────┐
│    Model Adapter 抽象层      │  ← 本课
│  ┌───────────────────────┐  │
│  │  BaseModelAdapter     │  │  ← ABC 抽象基类
│  └───────────────────────┘  │
│         ↙          ↘        │
│  OpenAIModelAdapter  VLLMModelAdapter
│  (dev 模式)          (prod 模式)
└─────────────────────────────┘
       ↓ 实际 HTTP 调用
OpenAI API / DashScope / vLLM Server
`

**上下游关系：**
- 上游：gents/（Top Agent、Search Agent、Critic Agent）
- 下游：外部 LLM/VLM API（OpenAI、DashScope、vLLM）

---

## 2. 模块设计理念

### 2.1 Strategy 模式（策略模式）

Model Adapter 是**策略模式（Strategy Pattern）**的典型应用：

- **BaseModelAdapter** — 抽象策略接口，定义 invoke、stream、ind_tools 三个核心方法
- **OpenAIModelAdapter** — 具体策略：通过 langchain-openai 的 ChatOpenAI 调用 OpenAI-compatible API
- **VLLMModelAdapter** — 具体策略：同样通过 ChatOpenAI 调用本地 vLLM 服务（API 兼容）
- **create_model_adapter()** — 策略工厂：根据 config.model.mode 自动选择策略

### 2.2 设计要点

1. **抽象基类（ABC）**：BaseModelAdapter 使用 Python bc.ABC 定义接口契约，强制子类实现 invoke 和 stream。
2. **工厂方法**：create_model_adapter() 根据配置的 mode 字段（dev/prod）返回对应适配器实例，调用方无需关心具体实现。
3. **延迟导入（Lazy Import）**：工厂函数内部导入具体适配器类，避免模块加载时触发 ChatOpenAI 初始化（需要 API key）。
4. **统一工具绑定**：ind_tools() 方法允许将工具定义绑定到模型，支持 LLM 工具调用（function calling）。
5. **langchain-openai 统一底层**：两种适配器都使用 ChatOpenAI，因为 vLLM 也提供 OpenAI-compatible API，实现代码复用。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **Python bc** | 抽象基类定义 |
| **LangChain ChatOpenAI** | OpenAI-compatible API 调用（langchain-openai 包） |
| **Async/Await** | 异步 invoke 和流式 astream |
| **AsyncGenerator** | 流式响应的类型标注 |

---

## 4. 数据模型与接口设计

### 4.1 抽象基类 (model_adapter/base.py)

`python
class BaseModelAdapter(ABC):
    """LLM/VLM 适配器抽象基类"""

    @abstractmethod
    async def invoke(self, messages: list[BaseMessage]) -> BaseMessage:
        """发送消息列表，返回单条响应。"""

    @abstractmethod
    async def astream(self, messages: list[BaseMessage]) -> AsyncGenerator[str, None]:
        """流式获取模型输出的 token。"""

    def bind_tools(self, tools: list[dict]) -> None:
        """绑定工具定义到模型（默认空操作，子类可覆盖）。"""
`

### 4.2 OpenAI 实现 (model_adapter/openai_adapter.py)

`python
class OpenAIModelAdapter(BaseModelAdapter):
    def __init__(self, model_name: str | None = None):
        config = get_config()
        dev = config.model.dev
        self.llm = ChatOpenAI(
            model=model_name or dev.llm_model,
            base_url=dev.base_url,
            api_key=dev.api_key if dev.api_key else None,
            temperature=0,
            max_retries=2,
        )

    async def invoke(self, messages) -> BaseMessage:
        return await self.llm.ainvoke(messages)

    async def astream(self, messages) -> AsyncGenerator[str, None]:
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content

    def bind_tools(self, tools: list[dict]) -> None:
        self.llm = self.llm.bind_tools(tools)
`

### 4.3 vLLM 实现 (model_adapter/vllm_adapter.py)

`python
class VLLMModelAdapter(BaseModelAdapter):
    def __init__(self, model_name: str | None = None):
        config = get_config()
        prod = config.model.prod
        self.llm = ChatOpenAI(
            model=model_name or prod.llm_model,
            base_url=prod.base_url,
            api_key=prod.api_key if prod.api_key else None,
            temperature=0,
        )

    async def invoke(self, messages) -> BaseMessage:
        return await self.llm.ainvoke(messages)

    async def astream(self, messages) -> AsyncGenerator[str, None]:
        async for chunk in self.llm.astream(messages):
            if chunk.content:
                yield chunk.content
`

### 4.4 工厂函数 (model_adapter/__init__.py)

`python
def create_model_adapter(model_name: str | None = None) -> BaseModelAdapter:
    """工厂函数：根据 config.model.mode 返回对应适配器"""
    config = get_config()
    if config.model.mode == 'dev':
        from vsa_agent.model_adapter.openai_adapter import OpenAIModelAdapter
        return OpenAIModelAdapter(model_name=model_name)
    elif config.model.mode == 'prod':
        from vsa_agent.model_adapter.vllm_adapter import VLLMModelAdapter
        return VLLMModelAdapter(model_name=model_name)
    else:
        raise ValueError(f'Unknown model mode: {config.model.mode}')
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/model_adapter/test_model_adapter.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestModelAdapterFactory | 	est_factory_returns_adapter | 工厂函数返回 BaseModelAdapter 实例 |
| TestModelAdapterFactory | 	est_factory_with_model_name | 可传入自定义 model_name |
| TestOpenAIModelAdapter | 	est_import_and_instantiate | OpenAIModelAdapter 可实例化，有 llm 属性 |
| TestVLLMModelAdapter | 	est_import_and_instantiate | VLLMModelAdapter 可实例化，有 llm 属性 |

> 注意：测试使用 @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}) mock 环境变量，避免真实 API 调用。

---

## 6. 动手练习

### 练习 1：理解策略模式

阅读 create_model_adapter() 的代码，回答：
1. 如果 config.model.mode 设置为 "dev"，会返回哪个适配器？
2. 如果需要在 dev 模式下使用 vLLM，需要修改哪个文件？
3. 为什么工厂函数内部使用 rom ... import 而不是文件顶部的 import？

### 练习 2：添加新的适配器

假设需要添加一个 AnthropicModelAdapter（使用 Anthropic Claude API），请写出：
1. 新建文件 model_adapter/anthropic_adapter.py 的代码框架
2. 需要在 create_model_adapter() 中添加什么逻辑？
3. 需要在 config.py 中添加什么配置字段？

### 练习 3：理解 bind_tools

阅读 OpenAIModelAdapter.bind_tools() 的实现，回答：
1. ind_tools 的作用是什么？
2. 为什么 VLLMModelAdapter 没有实现 ind_tools？
3. 如果一个工具列表被绑定后，LLM 的响应会有什么变化？

---

> **下一步**：学习 [L04: Search — 核心搜索（三路径路由）](L04-search.md)
