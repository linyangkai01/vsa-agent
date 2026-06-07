# vsa-agent 改造设计文档

> 从 NVIDIA VSS Blueprint 到工业安全视频分析Agent的全面改造方案

**目标：** 将NVIDIA VSS Blueprint全面改造为厂商无关的`vsa-agent`，用于工业安全检查场景（油田/矿山/工地），保留原项目16个核心设计理念，用开源框架逐层替代NVIDIA专有依赖。

**环境：** 开发期用OpenAI兼容API，生产期用vLLM本地部署。本地Windows写代码和单功能测试，实际部署在RTX 4090D 24GB服务器（Driver 550 / CUDA 12.4）。

---

## 一、NVIDIA依赖清单与开源替代方案

| NVIDIA专有依赖 | 作用 | 开源替代 | 学习要点 |
|---|---|---|---|
| `nvidia-nat==1.5.0` | Agent框架骨架 | LangChain + LangGraph | 理解Agent框架的设计模式 |
| `langchain-nvidia-ai-endpoints` | LLM API接入 | `langchain-openai` | LLM抽象层设计 |
| NIM容器 | 模型推理 | vLLM + Qwen3-VL-8B | 模型部署与推理优化 |
| NVIDIA pypi index | 私有包源 | PyPI标准源 | Python包管理 |
| NGC API Key | 认证 | 移除 | — |
| NVIDIA Embed1 | 视频embedding | sentence-transformers + CLIP/ViT | 多模态embedding原理 |

**核心认知：** `nvidia-nat`本质上是对LangChain/LangGraph的一层包装。拆掉它不代表重写，而是去掉中间层直接用底层框架。

## 二、保留的16个设计理念与开源实现

### 1. 插件注册模式 — 加工具不碰核心代码

**为什么：** 工具增删是最频繁的变更。每次加工具改核心代码会导致系统腐烂。

**NVIDIA方式：** Python entry_points + `@register_function`装饰器自动注册。

**开源实现：** 装饰器 + 全局注册表。

```python
# src/vsa_agent/registry.py
_TOOLS: dict[str, BaseTool] = {}

def register_tool(name: str):
    def decorator(cls):
        _TOOLS[name] = cls()
        return cls
    return decorator

class ToolRegistry:
    @classmethod
    def get_all(cls) -> list[BaseTool]:
        from vsa_agent.tools import register  # noqa: F401
        return list(_TOOLS.values())
```

### 2. 配置驱动一切 — 同份代码，两个环境

**为什么：** 开发用API省钱，生产用本地模型保证隐私。环境切换不能改代码。

**开源实现：** `config.yaml` + Pydantic Settings。

```yaml
# config.yaml
model:
  mode: dev  # dev | prod
  dev:
    provider: openai_compatible
    base_url: https://api.openai.com/v1
    llm_model: gpt-4o
    vlm_model: gpt-4o
  prod:
    provider: vllm
    base_url: http://localhost:8000/v1
    llm_model: Qwen3-VL-8B-Instruct
    vlm_model: Qwen3-VL-8B-Instruct
```

### 3. 类型化Agent决策

**为什么：** LLM输出必须结构化才能做自动化路由。

**开源实现：** LangGraph原生条件边。

```python
class AgentDecision(str, Enum):
    CALL_TOOL = "call_tool"
    RESPOND = "respond"

graph.add_conditional_edges("agent", router, {
    "call_tool": "tools",
    "respond": "__end__"
})
```

### 4. 后处理校验管线

**为什么：** LLM可能返回空值、编造URL、遗漏安全项。靠代码兜底。

**开源实现：** 责任链模式。

```python
class ValidationPipeline:
    async def run(self, output, context):
        issues = []
        for v in self.validators:
            result = await v.validate(output, context)
            if not result.passed:
                issues.extend(result.issues)
        return PostprocessingResult(passed=not issues, issues=issues)
```

内置：NonEmptyValidator → URLValidator → SafetyChecklistValidator。


### 5. Profile驱动部署

```yaml
# profiles/prod.yaml
services:
  vllm:
    image: vllm/vllm-openai:latest
    deploy:
      resources:
        reservations:
          devices: [driver: nvidia, device_ids: ["0"]]
```

### 6. Skills即Agent文档

agentskills.io规范的`SKILL.md`，含探针命令、前置条件、API示例。内容改为工业安全场景。

### 7. Critic Agent自检环

LangGraph conditional loop：Critic验证结果 → 不通过则回agent重试（最多3次）。

```python
def should_retry(state):
    if all(state["critic_result"].values()): return "respond"
    if state["retry_count"] >= 3: return "respond"
    return "retry"
```

### 8. 树形可配置评估体系

递归Pydantic模型声明评估标准树：

```yaml
safety_report_quality:
  method: average
  fields:
    completeness:
      method: llm_judge
      rules: ["是否覆盖所有检测区域", "是否列明违规时间"]
    accuracy:
      method: llm_judge
    format:
      method: regex_match
      pattern: ".*违规数量: \\d+.*"
```

### 9. 领域查询构建器

Builder模式杜绝字符串拼接ES查询。

```python
class SafetyIncidentQueryBuilder:
    BASE = {"query": {"bool": {"must": [], "filter": []}}}
    @classmethod
    def by_violation_type(cls, violation, start, end):
        query = deepcopy(cls.BASE)
        query["query"]["bool"]["must"].append({"term": {"violation_type": violation}})
        return query
```

### 10. Validator注册表

```python
_VALIDATOR_REGISTRY = {
    "non_empty": NonEmptyValidator,
    "url_check": URLValidator,
    "safety_checklist": SafetyChecklistValidator,
}
```

### 11. 意图感知Prompt模板

```python
SAFETY_PROMPTS = {
    "routine_inspection": """检查：1.未戴安全帽 2.未穿防护服 3.红区闯入""",
    "incident_investigation": """还原事件链：1.异常行为 2.行动轨迹 3.触发因素""",
}
```

### 12. URL翻译中间件

```python
def translate_url(url, vlm_mode, internal_host, external_host):
    if vlm_mode == "dev": return url.replace(internal_host, external_host)
    return url.replace(external_host, internal_host)
```

### 13. 三路搜索策略

根据输入特征自动路由：embedding搜索 / 属性搜索 / 融合搜索。

### 14. Agent输出分层模型

```python
class AgentOutput(BaseModel):
    messages: list[str]
    artifacts: dict[str, Any]     # PDF/图片/视频URL
    metadata: dict[str, Any]      # 耗时/置信度
    status: Literal["success", "partial", "error"]
```

### 15. 多模型推理模式适配

模型适配层根据模型名返回对应的reasoning参数格式。


### 16. AsyncMixin异步初始化

```python
class AsyncMixin:
    def __init__(self, *args, **kwargs):
        self.__storedargs = args, kwargs
    async def __ainit__(self, *args, **kwargs): ...
    def __await__(self):
        return self.__initobj().__await__()
# service = await AsyncService(config)
```

---

## 三、模块结构

```
vsa-agent/
├── config.yaml
├── pyproject.toml
├── docs/superpowers/
├── profiles/{dev,prod}.yaml
├── src/vsa_agent/
│   ├── config.py
│   ├── registry.py
│   ├── model_adapter/{base,openai_adapter,vllm_adapter}.py
│   ├── agents/{top_agent,search_agent,summary_agent,critic_agent}.py
│   ├── agents/postprocess/{pipeline,validators/}.py
│   ├── tools/{video_understanding,video_search,frame_extract,report_gen,query_builders}.py
│   ├── mcp/server.py
│   ├── api/{routes,health}.py
│   ├── evaluators/
│   └── utils/{async_mixin,retry,url_translation,frame_select,reasoning}.py
├── deployments/{docker-compose.yml,Dockerfile}
└── tests/{unit,integration}/
```

---

## 四、数据流

```
用户请求 → FastAPI → Top Agent (LangGraph)
                        │
              ┌────────┼────────┐
              ▼        ▼        ▼
           Search   Summary   Report
              │        │        │
              └────────┼────────┘
                       ▼
                Model Adapter
              ┌────────┴────────┐
              ▼                 ▼
        OpenAI API          vLLM
        (dev mode)       (prod mode)
```

---

## 五、技术栈总览

| 层级 | 技术 | 替代谁 |
|---|---|---|
| Agent框架 | LangChain + LangGraph | nvidia-nat |
| LLM接入 | langchain-openai | langchain-nvidia-ai-endpoints |
| 模型推理 | vLLM (Qwen3-VL-8B) | NIM容器 |
| 模型配置 | Pydantic Settings + YAML | .env扁平配置 |
| API服务 | FastAPI | (保留，去nat包装) |
| MCP服务 | fastmcp | nvidia-nat内建MCP |
| 视频处理 | FFmpeg + OpenCV | (保留) |
| Embedding | sentence-transformers + CLIP | NVIDIA Embed1 |
| 搜索引擎 | Elasticsearch | (保留) |
| 重试 | tenacity | (保留) |

---

## 六、实施阶段

### 阶段一：学习阶段

| # | 主题 | 产物 |
|---|------|------|
| 1.1 | LangChain + LangGraph 核心 | 最小Chat Agent |
| 1.2 | 模型适配层 | ModelAdapter抽象类 |
| 1.3 | Pydantic Settings + 配置驱动 | config.py |
| 1.4 | VLM视频理解原理 | FrameExtract工具 |
| 1.5 | fastmcp + MCP协议 | MCP server原型 |

### 阶段二：编码阶段（本地Windows）

| # | 模块 |
|---|------|
| 2.1 | 项目骨架 |
| 2.2 | Model Adapter + 单元测试 |
| 2.3 | Tool Registry + 视频帧提取 |
| 2.4 | Top Agent (LangGraph主编排) |
| 2.5 | Search Agent |
| 2.6 | Summary Agent |
| 2.7 | Critic Agent |
| 2.8 | Postprocessing管线 |
| 2.9 | MCP Server (fastmcp) |
| 2.10 | API Layer (FastAPI) |
| 2.11 | 集成测试 |

### 阶段三：服务器部署

| # | 内容 |
|---|------|
| 3.1 | vLLM部署Qwen3-VL-8B |
| 3.2 | ES + 视频存储 |
| 3.3 | Docker Compose生产配置 |
| 3.4 | 端到端验证 |

---

## 七、关键设计决策

| 决策 | 选择 | 理由 |
|---|---|---|
| Agent框架 | LangGraph | 与NVIDIA原设计一致 |
| MCP | fastmcp | 比官方sdk简单 |
| VLM | Qwen3-VL-8B | 开源、24GB可跑、工业场景好 |
| 部署 | vLLM而非Ollama | 生产级吞吐、OpenAI兼容API |

---

> **文档状态：** 待审核
> **下一步：** writing-plans → 详细实现计划

### 17. DAG架构 — Agent是图，不是链

**为什么这样设计：** 复杂的Agent工作流不适合线性执行。"先搜索→再摘要→校验→不通过回去重搜"这个流程天然是图结构。每个节点只关心自己的状态变换，路由逻辑独立。

**NVIDIA怎么做：** 原top_agent用LangGraph构建完整DAG：

```
plan ──→ plan_update → agent ⇄ tool
  │                       │
  └──→  postprocessing ←──┘
          │
       finalize → END
```

**开源实现：** 完全用LangGraph原生API，去掉nat包装。

```python
graph = StateGraph(AgentState)
graph.add_node("plan", self.plan_node)
graph.add_node("agent", self.agent_node)
graph.add_node("tool", self.tool_node)
graph.add_node("postprocess", self.postprocess_node)
graph.add_node("finalize", self.finalize_node)

# 条件边 — 同一个节点根据state走向不同目标
graph.add_conditional_edges("agent", self.decide_next, {
    AgentDecision.CALL_TOOL: "tool",
    AgentDecision.RESPOND: "postprocess",
})
# tool → agent 形成迭代循环（带最大次数限制）
graph.add_edge("tool", "agent")
```

**学习方法：** LangGraph让你把Agent的决策路径变成可追踪、可测试的图。每个节点是纯函数：输入State → 输出State。新增工作流=加节点+加边。

---

### 18. 节点级Streaming — 不止是token流

**为什么这样设计：** 用户需要知道Agent在想什么、在做什么。纯token streaming只能看到文字生成过程，看不到Agent的决策逻辑。

**NVIDIA怎么做：** LangGraph的`get_stream_writer()`在每个DAG节点内推送类型化chunk。

```python
# plan节点发射思考过程
writer = get_stream_writer()
writer(AgentMessageChunk(type=THOUGHT, content="分析：需先搜索视频片段..."))

# agent节点发射工具调用
writer(AgentMessageChunk(type=TOOL_CALL, content="正在调用: video_search(camera_3)"))

# finalize节点发射最终结果
writer(AgentMessageChunk(type=FINAL, content="报告已生成"))
```

**学习方法：** 这不是LLM token streaming——是图节点级的流式输出。前端能看到Agent完整的"思考→决策→行动→结果"链路。

---

### 19. 多Agent分层编排 — 子Agent如同工具

**为什么这样设计：** 视频搜索和报告生成是两个不同的专业Agent，但它们对外应该暴露统一接口。主Agent不需要知道调的是工具还是另一个Agent。

**NVIDIA怎么做：** `tool_or_subagent_node`统一处理工具和子Agent调用。

```python
if function_ref in self.sub_agents:
    sub_agent = self.sub_agents[function_ref]   # 子Agent
    async for chunk in sub_agent.stream(...):    # 也返回流式chunk
        writer(chunk)
else:
    result = await tool.ainvoke(...)             # 普通工具
```

**学习方法：** 子Agent和工具对外接口完全一致（输入→流式输出）。这是"Agent可嵌套"的基础——你可以把任意Agent包装成另一个Agent的工具。

---

### 20. Plan-then-Execute — 先规划，再执行

**为什么这样设计：** 没有计划的Agent是"反应式"的——LLM说调什么工具就调什么。对于多步骤任务（查事故→定位时段→提取帧→VLM分析→生成报告），不先规划容易迷失方向。

**NVIDIA怎么做：** plan节点用不带工具绑定的LLM生成行动计划，plan_update节点在每次工具调用后更新进度。

```
plan节点输出：
  "步骤1: 搜索事故相关片段
   步骤2: 提取关键帧(每5秒1帧)
   步骤3: VLM逐帧分析安全违规
   步骤4: 聚合生成安全报告"

plan_update更新：
  "已完成: 步骤1(15个片段), 步骤2(60帧)
   进行中: 步骤3 VLM分析... 待完成: 步骤4"
```

**学习方法：** Plan-then-Execute把Agent从"反应式工具调用"升级为"计划驱动的任务执行"。这对工业场景的长时间巡检特别关键。

---

### 21. LangGraph Checkpointer — 状态持久化+异常恢复

**为什么这样设计：** Agent执行可能持续几分钟甚至几十分钟。如果中途崩溃，不能从头开始。需要从最近的checkpoint恢复。

**NVIDIA怎么做：** `InMemorySaver`为每次图遍历创建checkpoint。

```python
checkpointer = InMemorySaver()
graph = graph.compile(checkpointer=checkpointer)

# 恢复：从上次保存的state继续
previous_state = graph.get_state({
    "configurable": {"thread_id": thread_id}
}).values
```

**学习方法：** LangGraph的checkpointer不光做持久化——它是异常恢复、人工审核、分支执行的基础。每个checkpoint保存完整的state快照。

---

### 22. 图级防护 — recursion_limit + try/except

```python
# 防止死循环
async for chunk in self.graph.astream(
    input=input_state,
    config={"recursion_limit": self.max_iterations},  # 最大迭代
    stream_mode="custom"
):
    yield chunk
except Exception:
    # 单次失败不崩整个对话
    writer(AgentMessageChunk(type=ERROR, content=str(ex)))
```

**学习方法：** Agent图是"活的"——可能因为LLM幻觉陷入死循环。recursion_limit是硬防护，try/except是软防护。两者缺一不可。

---

