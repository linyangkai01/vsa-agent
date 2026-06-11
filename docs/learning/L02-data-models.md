# L02: Data Models — 核心数据结构

## 1. 模块在业务流中的位置

Data Models 定义了 VSA Agent 系统中**所有核心数据结构**，是各模块之间传递数据的"契约"。这些数据模型被 Agents、Tools、Video Analytics 等模块广泛引用。

`
Agents ──→ Data Models ←── Tools
   ↑                          ↑
   └──── Video Analytics ─────┘
`

**上下游关系：**
- 上游：无（纯数据定义，不依赖其他业务模块）
- 下游：gents/（AgentState、AgentDecision）、	ools/search.py（Incident）、ideo_analytics/（Incident, Location, Place）

---

## 2. 模块设计理念

### 2.1 分层数据模型

系统定义了**三层数据模型**，分别服务于不同抽象层级：

| 层级 | 文件 | 用途 |
|------|------|------|
| **Agent 层** | gents/data_models.py | Agent 状态跟踪、决策枚举、流式输出 |
| **视频搜索层** | data_models/vss.py | 视频元数据、搜索偏移量 |
| **事件分析层** | ideo_analytics/nvschema.py | 结构化事件描述（Incident、Location、Place） |

### 2.2 设计要点

1. **枚举驱动条件边（Enum-driven Conditional Edges）**：AgentDecision 枚举（CALL_TOOL / RESPOND）直接用于 LangGraph 的条件边路由，将 Agent 决策与图拓扑解耦。
2. **状态即图状态（State as Graph State）**：AgentState 直接作为 LangGraph 的 StateSchema，包含消息历史、中间步骤、迭代计数等完整对话状态。
3. **NVIDIA 模式对齐**：Incident 数据模型对齐 NVIDIA VSS（Video Search & Summarization）Schema，确保与 NVIDIA 生态兼容。
4. **向后兼容重导出**：data_models/vss.py 从 ideo_analytics/nvschema.py 重导出 Incident，保持旧导入路径可用。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **Pydantic v2** (BaseModel, Field) | Agent 数据模型定义（状态、输出、流式块） |
| **Python dataclasses** | 视频元数据、事件模型定义（轻量级） |
| **Python enum.StrEnum** | 枚举类型（AgentDecision、AgentMessageChunkType） |
| **LangChain BaseMessage** | 与 LangChain/LangGraph 的消息格式兼容 |

---

## 4. 数据模型与接口设计

### 4.1 Agent 层数据模型 (gents/data_models.py)

`python
class AgentDecision(enum.StrEnum):
    """Agent 节点决策 — 驱动 LangGraph 条件边"""
    CALL_TOOL = 'call_tool'   # 需要调用工具
    RESPOND = 'respond'       # 可以回复用户

class AgentMessageChunkType(enum.StrEnum):
    """流式消息块类型"""
    THOUGHT = 'thought'       # 思考过程
    TOOL_CALL = 'tool_call'   # 工具调用
    FINAL = 'final'           # 最终回复
    ERROR = 'error'           # 错误信息

class AgentMessageChunk(BaseModel):
    """流式输出块"""
    type: AgentMessageChunkType = AgentMessageChunkType.THOUGHT
    content: str = ''

class AgentState(BaseModel):
    """Agent 对话状态 — 直接作为 LangGraph StateSchema"""
    current_message: BaseMessage | None = None    # 当前用户消息
    agent_scratchpad: list[BaseMessage] = []       # 中间思考 + 工具结果
    conversation_history: list[BaseMessage] = []   # 历史对话
    iteration_count: int = 0                       # LLM 调用次数
    final_answer: str = ''                         # 最终答案
    plan: str = ''                                 # (预留) 计划
    previous_conversation: str = ''                # (预留) 前序对话
    llm_reasoning: bool = False                    # (预留) LLM 推理
    vlm_reasoning: bool | None = None              # (预留) VLM 推理
    search_source_type: str = 'video_file'         # 搜索源类型

class AgentOutput(BaseModel):
    """标准化 Agent 输出"""
    messages: list[str] = []
    side_effects: dict = {}
    metadata: dict = {}
    status: str = 'success'                        # success / error
`

### 4.2 视频搜索层数据模型 (data_models/vss.py)

`python
@dataclass
class MediaInfoOffset:
    """视频元数据 + 当前处理偏移量"""
    video_path: str = ""
    duration_sec: float = 0.0       # 视频总时长（秒）
    fps: float = 0.0                # 帧率
    total_frames: int = 0           # 总帧数
    current_offset_sec: float = 0.0 # 当前处理位置（秒）
    metadata: dict[str, Any] = {}   # 扩展元数据
`

### 4.3 事件分析层数据模型 (ideo_analytics/nvschema.py)

`python
@dataclass
class Location:
    """事件发生地点"""
    name: str = ""
    description: str = ""
    coordinates: tuple[float, float] | None = None  # (纬度, 经度)
    zone: str = ""                    # 区域，如 "red_zone", "loading_dock"
    metadata: dict[str, Any] = {}

@dataclass
class Place:
    """地点内的具体位置"""
    name: str = ""
    description: str = ""
    location: Location | None = None
    metadata: dict[str, Any] = {}

@dataclass
class Incident:
    """检测到的事件 — 对齐 NVIDIA VSS Schema"""
    id: str = ""
    timestamp_sec: float = 0.0       # 事件时间戳（秒）
    duration_sec: float = 0.0        # 事件持续时间
    description: str = ""            # 事件描述
    severity: str = "unknown"        # low / medium / high / critical
    category: str = ""               # 类别：no_helmet, fall, fire, intrusion
    subcategory: str = ""            # 子类别
    location: Location | None = None
    place: Place | None = None
    confidence: float = 0.0          # 置信度
    detected_objects: list[str] = [] # 检测到的物体
    detected_actions: list[str] = [] # 检测到的行为
    frame_indices: list[int] = []    # 相关帧索引
    metadata: dict[str, Any] = {}
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/data_models/test_agent_data_models.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestAgentDecision | 	est_values | 枚举值正确：CALL_TOOL = "call_tool", RESPOND = "respond" |
| TestAgentMessageChunkType | 	est_values | 枚举值正确：THOUGHT = "thought", FINAL = "final" |
| TestAgentMessageChunk | 	est_defaults | 默认构造：type=THOUGHT, content="" |
| TestAgentState | 	est_defaults | 默认状态：current_message=None, iteration_count=0 |
| TestAgentState | 	est_with_message | 传入 HumanMessage 后正确存储 |
| TestAgentOutput | 	est_defaults | 默认输出：messages=[], status="success" |
| TestAgentOutput | 	est_error_status | 可设置 status="error" |

### 测试文件：	ests/unit/data_models/test_vss_data_models.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestMediaInfoOffset | 	est_defaults | 默认构造：video_path="", duration_sec=0.0 |
| TestMediaInfoOffset | 	est_custom_values | 自定义值正确设置 |
| TestIncident | 	est_defaults | 默认构造：description="", severity="unknown" |
| TestIncident | 	est_with_values | 自定义值正确设置 |

---

## 6. 动手练习

### 练习 1：理解数据流

追踪一次视频分析请求的数据流，回答：
1. 用户输入首先存储在 AgentState 的哪个字段？
2. Agent 调用工具时，AgentDecision 的值是什么？
3. VLM 分析完成后，事件信息存储在哪个数据模型中？

### 练习 2：扩展 Incident 模型

假设需要为 Incident 添加一个 evidence_urls: list[str] 字段，用于存储事件相关的证据图片 URL。请写出：
1. 需要在哪个文件中修改？
2. 使用 dataclasses 的 ield(default_factory=list) 如何添加该字段？
3. 对应的测试用例应该验证什么？

### 练习 3：创建自定义状态

参考 AgentState，设计一个 SearchAgentState，包含：
- query: str — 原始搜索查询
- decomposed_queries: list[str] — 分解后的子查询
- search_results: list[Incident] — 搜索结果
- status: str — 搜索状态（"searching" / "completed" / "failed"）

请写出完整的 Pydantic 模型定义。

---

> **下一步**：学习 [L03: Model Adapter — LLM/VLM 抽象层](L03-model-adapter.md)
