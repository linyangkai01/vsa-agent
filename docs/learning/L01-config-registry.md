# L01: Config + Registry — 系统基石

## 1. 模块在业务流中的位置

Config 和 Registry 是整个 VSA Agent 系统的**最底层基础设施**，被所有上层模块依赖。

`
API / Agents / Tools / Model Adapter ...
        ↑         依赖        ↓
   ┌─────────────────────────────────┐
   │        Config + Registry        │  ← 本课
   └─────────────────────────────────┘
`

- **Config**：提供全局统一的配置读取入口。任何模块需要获取模型参数、Agent 行为参数、服务器端口等，都通过 get_config() 获取。
- **Registry**：提供工具/模块的自动发现和注册机制。Agent 在运行时通过 ToolRegistry.get_all() 获取所有已注册的工具函数，无需硬编码。

**上下游关系：**
- 上游：无（最底层）
- 下游：main.py（启动入口）、gents/（Agent 编排）、	ools/（工具实现）、model_adapter/（模型适配）

---

## 2. 模块设计理念

### Config 的设计理念

1. **分层配置（Hierarchical Config）**：使用 Pydantic BaseModel 嵌套结构，将配置按领域拆分（ModelConfig、AgentConfig、ServerConfig、ToolsConfig、PromptsConfig），每个子配置独立管理默认值。
2. **环境分离（Dev/Prod Separation）**：ModelConfig 内部分为 dev 和 prod 两种模式，通过 mode 字段切换。开发环境使用 OpenAI-compatible API（如 DashScope），生产环境使用本地 vLLM 服务。
3. **YAML + 环境变量覆盖**：配置从 config.yaml 加载，路径可通过环境变量 VSA_CONFIG 覆盖，便于不同部署环境使用不同配置。
4. **单例模式（Singleton）**：get_config() 使用模块级全局变量 _config 实现惰性加载的单例模式，确保整个应用生命周期内配置只加载一次。

### Registry 的设计理念

1. **装饰器模式（Decorator Pattern）**：使用 @register_tool(name, description) 装饰器，让工具函数在定义时自动注册到全局注册表，无需手动维护工具列表。
2. **延迟加载（Lazy Loading）**：_ensure_loaded() 在首次访问注册表时根据 config.yaml 中的 	ools.enabled_modules 列表动态导入模块，避免启动时加载所有工具。
3. **统一发现机制**：通过 ToolRegistry 类提供统一的 get_all()、get()、list_tools() 接口，上层 Agent 无需关心工具的具体实现位置。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **Pydantic v2** | 配置模型的声明式定义、类型校验、默认值管理 |
| **PyYAML** | 从 YAML 文件加载配置 |
| **Python importlib** | 动态导入工具模块 |
| **Python os.environ** | 环境变量读取（配置路径覆盖） |

---

## 4. 数据模型与接口设计

### 4.1 Config 数据模型

`
AppConfig
├── model: ModelConfig
│   ├── mode: "dev" | "prod"       (default: "dev")
│   ├── dev: ModelDevConfig
│   │   ├── provider: str          (default: "openai_compatible")
│   │   ├── base_url: str          (default: "https://api.openai.com/v1")
│   │   ├── api_key: str
│   │   ├── llm_model: str         (default: "gpt-4o")
│   │   └── vlm_model: str         (default: "gpt-4o")
│   └── prod: ModelProdConfig
│       ├── provider: str          (default: "vllm")
│       ├── base_url: str          (default: "http://localhost:8000/v1")
│       ├── api_key: str
│       ├── llm_model: str         (default: "Qwen3-VL-8B-Instruct")
│       └── vlm_model: str         (default: "Qwen3-VL-8B-Instruct")
├── tools: ToolsConfig
│   └── enabled_modules: list[str] (default: ["vsa_agent.tools.echo_tool"])
├── agent: AgentConfig
│   ├── max_iterations: int        (default: 15)
│   ├── planning_enabled: bool     (default: True)
│   ├── postprocessing_enabled: bool (default: True)
│   ├── log_level: str             (default: "INFO")
│   └── max_history: int           (default: 10)
├── server: ServerConfig
│   ├── host: str                  (default: "0.0.0.0")
│   └── port: int                  (default: 8000)
└── prompts: PromptsConfig
    ├── default_system: str
    ├── safety_routine_inspection: str
    ├── safety_incident_investigation: str
    └── vlm_format_instruction: str
`

### 4.2 核心函数签名

`python
# config.py
class AppConfig(BaseModel):
    @classmethod
    def from_yaml(cls, path: str | Path = "config.yaml") -> "AppConfig"
        """从 YAML 文件加载配置并返回 AppConfig 实例。"""

def get_config() -> AppConfig
    """获取全局单例配置。首次调用时从 YAML 加载，后续返回缓存实例。"""

# registry.py
def register_tool(name: str, description: str = '') -> Callable
    """装饰器：将函数注册到全局工具注册表。"""

class ToolRegistry:
    @classmethod
    def get_all(cls) -> dict[str, Callable]
        """获取所有已注册的工具函数字典。"""

    @classmethod
    def get(cls, name: str) -> Callable | None
        """按名称获取单个工具函数，不存在时返回 None。"""

    @classmethod
    def list_tools(cls) -> list[dict[str, str]]
        """获取工具列表（名称 + 描述），用于 LLM 工具选择。"""
`

### 4.3 典型使用流程

`python
# 1. 获取配置
cfg = get_config()
print(cfg.model.mode)           # "dev"
print(cfg.server.port)          # 8000

# 2. 注册工具
@register_tool("my_tool", description="My custom tool")
async def my_tool(param: str) -> str:
    return f"Processed: {param}"

# 3. 使用注册表
tools = ToolRegistry.get_all()      # {"my_tool": <function>, "echo": <function>, ...}
tool_func = ToolRegistry.get("echo")  # 获取单个工具
tool_list = ToolRegistry.list_tools() # [{"name": "echo", "description": "..."}, ...]
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/test_config.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestAppConfig | 	est_default_construction | 默认构造的 AppConfig 各字段默认值正确 |
| TestAppConfig | 	est_from_yaml | 从临时 YAML 文件加载配置，验证覆盖默认值 |
| TestModelConfig | 	est_dev_defaults | ModelConfig 的 dev 模式默认 LLM 模型为 "gpt-4o" |
| TestPromptsConfig | 	est_defaults_empty | PromptsConfig 默认值为空字符串 |
| TestGetConfig | 	est_returns_appconfig | get_config() 返回 AppConfig 实例 |

### 测试文件：	ests/unit/test_registry.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestRegisterTool | 	est_registers_function | @register_tool 装饰器正确将函数注册到全局注册表 |
| TestToolRegistry | 	est_get_returns_none_for_missing | 查询不存在的工具返回 None |
| TestToolRegistry | 	est_list_tools_returns_list | list_tools() 返回包含 
ame 字段的列表 |

---

## 6. 动手练习

### 练习 1：理解配置加载

阅读 config.yaml 文件，回答以下问题：
1. 开发环境（dev）使用的 LLM 模型是什么？VLM 模型是什么？
2. 生产环境（prod）使用的 LLM 模型是什么？
3. 当前启用了哪些工具模块？

### 练习 2：扩展配置模型

假设需要新增一个 LoggingConfig 子配置，包含 level（str，默认 "INFO"）和 ile_path（str，默认 "logs/app.log"）两个字段。请写出：

1. 在 config.py 中需要添加的 Pydantic 模型类
2. 如何在 AppConfig 中引用它
3. 对应的 YAML 配置片段

### 练习 3：自定义注册工具

参考 echo_tool.py 的实现，编写一个 hello_tool：
- 工具名称："hello"
- 描述："Say hello to a person"
- 接收参数：
ame: str
- 返回："Hello, {name}!"
- 使用 @register_tool 装饰器注册

---

> **下一步**：学习 [L02: Data Models — 核心数据结构](L02-data-models.md)
