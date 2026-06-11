# L06: Agents — 业务流程编排

## 1. 模块在业务流中的位置

Agents 是 VSA Agent 的**业务流程编排层**，使用 LangGraph 构建有向无环图（DAG）来编排整个分析流程。这是系统的"大脑"，负责理解用户意图、调用合适的工具、验证结果并生成最终回复。

`
用户输入
    ↓
┌──────────────────┐
│   Top Agent      │  ← 本课核心：LangGraph DAG
│  (agent_node)    │
│       ↓          │
│  decide_next     │──→ CALL_TOOL → tool_node → (back to agent)
│       ↓          │
│   RESPOND        │
│       ↓          │
│  finalize_node   │
└──────────────────┘
       ↓
┌──────────────────┐
│  Search Agent    │  ← 搜索子流程
│  (三路径路由)     │
└──────────────────┘
       ↓
┌──────────────────┐
│  Critic Agent    │  ← VLM 验证子流程
│  (Self-Check)    │
└──────────────────┘
`

**上下游关系：**
- 上游：main.py（启动入口）、pi/routes.py（API 路由）
- 下游：	ools/（所有工具）、model_adapter/（LLM/VLM 调用）、
egistry.py（工具发现）

---

## 2. 模块设计理念

### 2.1 LangGraph DAG 架构

Top Agent 使用 LangGraph 构建了一个三节点的有向图：

`
                    ┌──────────┐
                    │  agent   │  ← LLM 调用 + 工具绑定
                    └────┬─────┘
                         │ decide_next
                    ┌────┴─────┐
                    │          │
               CALL_TOOL   RESPOND
                    │          │
               ┌────┴──┐  ┌───┴──────┐
               │ tool  │  │ finalize │
               └────┬──┘  └───┬──────┘
                    │         │
                    └──agent──┘    END
`

| 节点 | 功能 |
|------|------|
| **agent_node** | 调用 LLM，绑定工具，获取响应 |
| **tool_node** | 执行 LLM 请求的工具调用 |
| **finalize_node** | 生成最终回复，保存对话历史 |

### 2.2 设计要点

1. **条件边（Conditional Edge）**：decide_next() 根据 AgentDecision 枚举决定下一个节点，实现 ReAct 模式的自动循环。
2. **工具动态绑定**：_build_langchain_tools() 从 ToolRegistry 动态获取所有已注册工具，转换为 LangChain StructuredTool，自动生成 JSON Schema。
3. **参数注入**：_INJECTION_PARAMS 集合定义了需要从工具函数签名中排除的注入参数（如 store、model_adapter），这些参数由框架注入而非 LLM 生成。
4. **结果截断**：_truncate_result() 对工具返回结果进行截断（默认 800 字符），避免 LLM 上下文溢出。
5. **帧数据优化**：_sanitize_tool_result() 对 rame_extract 结果特殊处理，将 base64 帧数据替换为引用计数，减少上下文占用。

### 2.3 Search Agent（搜索子流程）

Search Agent 封装了 Lesson 4 的三路径搜索逻辑，作为注册工具供 Top Agent 调用：

- 接收 SearchAgentInput（query, agent_mode, max_results 等）
- 调用 decompose_query() 分解查询
- 执行三路径路由搜索
- 可选调用 Critic Agent 验证结果

### 2.4 Critic Agent（验证子流程）

Critic Agent 实现了 **Self-Check Loop（Design Pattern #7）**：

- 接收搜索结果的视频列表
- 对每个视频调用 VLM，检查是否满足用户查询的所有条件
- 返回 CONFIRMED / REJECTED / UNVERIFIED
- 所有条件必须满足才判定为 CONFIRMED

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **LangGraph** | DAG 图构建、节点编排、条件边 |
| **LangChain StructuredTool** | 工具 Schema 生成 |
| **LangGraph InMemorySaver** | 对话状态持久化（内存） |
| **Python inspect / get_type_hints** | 工具函数签名反射 |
| **Pydantic create_model** | 动态创建工具参数 Schema |

---

## 4. 数据模型与接口设计

### 4.1 Top Agent 核心函数

`python
async def agent_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """Agent 节点：调用 LLM，绑定工具，返回响应。"""

async def tool_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """工具节点：执行 LLM 请求的工具调用。"""

async def finalize_node(state: AgentState, config: RunnableConfig) -> AgentState:
    """最终节点：生成回复，保存对话历史。"""

def decide_next(state: AgentState) -> str:
    """条件边决策：根据 AgentDecision 返回下一个节点名称。"""

async def build_graph() -> CompiledStateGraph:
    """构建并编译 LangGraph DAG。"""

def _build_langchain_tools() -> list[StructuredTool]:
    """从 ToolRegistry 动态构建 LangChain 工具列表。"""

def _build_tool_schema(fn) -> type[BaseModel] | None:
    """从工具函数签名动态生成 Pydantic Schema。"""
`

### 4.2 Search Agent 接口

`python
class SearchAgentInput(BaseModel):
    query: str                          # 搜索查询
    agent_mode: bool = True             # 启用 LLM 查询分解
    use_attribute_search: bool | None = None
    max_results: int = 5                # 最大结果数
    top_k: int | None = None
    start_time: str | None = None
    end_time: str | None = None
    source_type: str = "video_file"
    use_critic: bool = True             # 是否使用 Critic 验证

@register_tool("search_agent", description="...")
async def search_agent_tool(
    query: str,
    agent_mode: bool = True,
    max_results: int = 5,
) -> str:
    """搜索 Agent 工具：执行完整搜索流程。"""

def _to_search_results(raw: list) -> list[SearchResult]:
    """???????? SearchResult ????? dict?SearchResult?model_dump ???"""


async def execute_search(
    search_input: SearchAgentInput,
    model_adapter=None,
    embed_search=None,
    attribute_search=None,
) -> SearchOutput:
    """执行搜索：查询分解 + 三路径路由。"""
`

### 4.3 Critic Agent 接口

`python
class CriticAgentInput(BaseModel):
    query: str
    videos: list[VideoInfo]
    evaluation_count: int | None = None

class CriticAgentOutput(BaseModel):
    video_results: list[VideoResult]

class VideoInfo(BaseModel, frozen=True):
    sensor_id: str
    start_timestamp: str
    end_timestamp: str

class VideoResult(BaseModel):
    video_info: VideoInfo
    result: CriticAgentResult  # CONFIRMED / REJECTED / UNVERIFIED
    criteria_met: dict[str, bool] | None = None

@register_tool("critic_agent", description="...")
async def critic_agent_tool(query: str, videos_json: str) -> str:
    """Critic Agent 工具：VLM 验证搜索结果。"""

async def execute_critic(
    critic_input: CriticAgentInput,
    model_adapter=None,
) -> CriticAgentOutput:
    """执行 VLM 验证。"""
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/agents/test_top_agent.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestDecideNext | 	est_empty_scratchpad_returns_respond | 空 scratchpad 返回 RESPOND |
| TestDecideNext | 	est_tool_call_returns_call_tool | 有 tool_calls 时返回 CALL_TOOL |
| TestDecideNext | 	est_ai_message_no_tool_calls_returns_respond | 无 tool_calls 时返回 RESPOND |
| TestBuildGraph | 	est_graph_compiles | DAG 编译成功 |

### 测试文件：	ests/unit/agents/test_search_agent.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestSearchAgentInput | 	est_defaults | 默认值正确 |
| TestSearchAgentInput | 	est_with_values | 自定义值正确设置 |
| TestSearchAgentConfig | 	est_defaults | 默认配置 |

### 测试文件：	ests/unit/agents/test_critic_agent.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestVideoInfo | 	est_required_fields | 必填字段正确 |
| TestCriticAgentInput | 	est_minimal | 最小输入构造 |
| TestCriticAgentResult | 	est_values | 枚举值正确 |
| TestVideoResult | 	est_with_criteria | 带 criteria 的结果 |
| TestCriticAgentOutput | 	est_with_results | 输出容器 |
| TestGetJsonFromString | 	est_strips_json_markdown | 去除 markdown 代码块标记 |
| TestGetJsonFromString | 	est_plain_string | 纯 JSON 字符串直接返回 |
| TestExecuteCritic | 	est_with_mock_adapter | mock VLM 验证完整流程 |

---

## 6. 动手练习

### 练习 1：理解 LangGraph DAG

画出 Top Agent 的 DAG 图，并回答：
1. 当 LLM 返回 tool_calls 时，下一个节点是什么？
2. tool_node 执行完后，下一个节点是什么？
3. 什么情况下会进入 finalize_node？
4. 如果 max_iterations=15，这个限制在哪里实现？

### 练习 2：添加新节点

假设需要添加一个 logging_node，在每个工具调用前后记录日志：
1. 需要在 	op_agent.py 中添加什么代码？
2. 如何在 DAG 中插入这个节点？
3. 如何确保 logging_node 不影响原有流程？

### 练习 3：理解 Critic Agent 的 Self-Check

回答以下问题：
1. Critic Agent 如何判断一个搜索结果是否"确认"？
2. 如果 VLM 返回 {"person": true, "red_shirt": false}，结果是什么？
3. 为什么 VideoInfo 使用 rozen=True？
4. 如果 VLM 调用失败，结果状态是什么？

---

> **下一步**：学习 [L07: Video Analytics — 事件分析层](L07-video-analytics.md)
