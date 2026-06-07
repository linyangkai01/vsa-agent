# vsa-agent Construction Guide

> 建设指南：从NVIDIA VSS Blueprint学到的框架设计 + 开源替代方案 + 开发惯例

---

## 一、原项目框架全景

### 1.1 三层架构

`
agent/                          # Agent代码（Python）
├── pyproject.toml               # 包定义 + nat.components入口点
├── uv.lock                      # 依赖锁定
├── docker/Dockerfile            # 多阶段Docker构建（builder → runtime）
├── app/video_search_frag/       # 功能扩展（插件模式）
│   ├── pyproject.toml            # 独立安装包，entry_points注册到nat
│   └── configs/                  # 功能专属配置
├── src/vss_agents/              # 核心源代码
│   ├── __init__.py               # 空文件（模块入口留空）
│   ├── prompt.py                 # Prompt常量集中管理
│   ├── agents/                   # Agent工作流
│   │   ├── register.py           # import触发注册
│   │   ├── data_models.py        # AgentDecision, AgentMessageChunk, AgentOutput
│   │   ├── top_agent.py          # 主编排Agent（LangGraph DAG）
│   │   ├── search_agent.py       # 搜索Agent
│   │   ├── report_agent.py       # 报告Agent
│   │   └── postprocess/          # 后处理校验管线
│   │       ├── postprocessing_node.py
│   │       └── validators/       # 可插拔校验器
│   ├── tools/                    # 工具集
│   │   ├── register.py           # import触发工具注册
│   │   ├── search.py             # 核心搜索工具
│   │   ├── video_understanding.py # VLM视频理解
│   │   └── ...                   # 每个工具独立文件
│   ├── api/                      # FastAPI层
│   ├── video_analytics/          # ES查询、embedding
│   ├── embed/                    # 多模态embedding
│   ├── utils/                    # 工具函数
│   ├── evaluators/               # 评估体系
│   └── data_models/              # 领域数据模型
├── tests/unit_test/              # 测试镜像源码结构
│   ├── conftest.py               # 公共fixtures
│   ├── agents/test_top_agent.py
│   ├── tools/test_search.py
│   └── ...
└── stubs/                        # 类型桩文件
`

### 1.2 包注册机制

原项目通过Python entry_points实现插件发现：

`
pyproject.toml:
  [project.entry-points.'nat.components']
  vss_tools = "vss_agents.tools.register"
  vss_agents = "vss_agents.agents.register"
`

每个register.py只做import：
`python
# tools/register.py
from . import search
from . import video_understanding
`

Import触发模块顶层的nat装饰器或框架钩子执行注册。

**vs vsa-agent替代：** 我们用ToolRegistry + @register_tool装饰器实现相同模式，去掉了nat框架层。

---

## 二、开发惯例（从原项目继承）

### 2.1 代码风格

- **Section标题**: # ====={ Name }=====
- **常量**: 模块级UPPER_SNAKE_CASE全大写
- **日志**: 每个agent/tool节点入口写logger.debug()
- **导入**: 每行一个import，按stdlib → third-party → first-party分组
- **类型提示**: 所有公开函数必须有类型注解
- **Docstring**: 简洁、祈使语气（"Build the graph"而非"Builds the graph"）

### 2.2 文件职责

| 文件模式 | 职责 | 不做什么 |
|---|---|---|
| 
egister.py | 只做import触发注册 | 不写业务逻辑 |
| __init__.py | 空文件或导出公共API | 不做import依赖树 |
| data_models.py | Pydantic模型定义 | 不写业务逻辑 |
| conftest.py | pytest fixtures | 不写测试用例 |
| prompt.py | Prompt字符串常量 | 不写函数逻辑 |

### 2.3 模块组织原则

1. **一个文件一个职责** — search_agent.py只管搜索，不碰报告生成
2. **tools与agents分离** — tools是被调用的原子操作，agents是编排工具的工作流
3. **utils是纯函数** — 不依赖状态，不import agent/tool模块
4. **测试镜像源码目录** — 	ests/unit/agents/test_top_agent.py对应src/vsa_agent/agents/top_agent.py

### 2.4 TDD流程

原项目的测试模式：

`python
# 1. 测试常量 → 断言类型和内容
def test_prompt_is_string():
    assert isinstance(VSS_SUMMARIZE_PROMPT, str)
def test_prompt_contains_placeholders():
    assert "{user_query}" in VSS_SUMMARIZE_PROMPT

# 2. 测试工具 → mock外部依赖
async def test_search_basic(mock_llm):
    result = await execute_search(query="test", llm=mock_llm)
    assert len(result.results) > 0

# 3. 测试Agent → 用mock LLM模拟不同响应
async def test_agent_routes_to_tool(mock_llm_with_tool_calls):
    state = await agent_node(AgentState(current_message="search for x"))
    assert state.pending_tool_calls  # 验证路由决策

# 4. 覆盖率测试 → 常量和边缘情况
def test_coverage():
    assert SOME_LIST  # 不为空
`

**TDD顺序：** 先写测试（红） → 最小实现（绿） → commit → 重构（保持绿）

---

## 三、模块依赖图

`
FastAPI (api/routes.py)  →  build_graph()  →  agent_node()
MCP (mcp/server.py)      →  build_graph()       │
                                                  ├── model_adapter.create_model_adapter()
                                                  ├── registry.ToolRegistry.get_all()
                                                  └── data_models.AgentDecision
`

**依赖方向规则：**
- pi/ → gents/ → model_adapter/ + 
egistry/ → config/
- 不允许反向依赖（config不能import agents）
- utils/ 被所有人import，但不import任何人

---

## 四、当前项目状态

### 4.1 已完成模块

| 模块 | 文件 | 设计理念 |
|---|---|---|
| 配置系统 | config.py, config.yaml | #2 配置驱动 |
| 模型适配 | model_adapter/{base,openai,vllm}_adapter.py | #15 多模型适配 + #13 策略模式 |
| 工具注册 | 
egistry.py, 	ools/{register,echo_tool}.py | #1 插件注册 + #10 注册表 |
| Agent DAG | gents/{data_models,register,top_agent}.py | #3 类型决策 + #17 DAG + #18 Streaming |
| API层 | pi/{routes,health}.py | — |
| MCP层 | mcp/server.py | fastmcp工具暴露 |

### 4.2 待实现模块

| 优先级 | 模块 | 对应设计理念 |
|---|---|---|
| P0 | 	ools/video_understanding.py | VLM视频理解工具 ✅ **DONE** |
| P0 | 	ools/frame_extract.py | 视频帧提取（OpenCV） ✅ **DONE** |
| P0 | gents/search_agent.py | #13 三路搜索策略 |
| P0 | gents/summary_agent.py | 长视频摘要 + 安全报告 |
| P1 | gents/critic_agent.py | #7 Critic自检环 |
| P1 | gents/postprocess/ | #4 后处理管线 + #10 Validator注册表 |
| P1 | 	ools/query_builders.py | #9 领域查询构建器 |
| P2 | evaluators/ | #8 树形评估配置 |
| P2 | utils/{async_mixin,url_translation,retry}.py | #16 #12 |
| P2 | skills/ | #6 Skills即文档 |

---

## 五、开发工作流

### 5.1 新增一个工具

1. 在 	ests/unit/tools/ 创建 	est_my_tool.py（先写测试）
2. 在 src/vsa_agent/tools/ 创建 my_tool.py
3. 用 @register_tool('my_tool') 装饰器注册
4. 在 	ools/register.py 加 rom . import my_tool
5. 跑 pytest tests/unit/tools/test_my_tool.py -v
6. commit

### 5.2 新增一个Agent

1. 在 	ests/unit/agents/ 创建 	est_my_agent.py
2. 在 src/vsa_agent/agents/ 创建 my_agent.py
   - 用LangGraph StateGraph构建DAG
   - 节点函数签名: sync def node(state: AgentState, config: RunnableConfig) -> AgentState
   - 流式输出: writer = get_stream_writer(); writer(AgentMessageChunk(...))
3. 在 gents/register.py 加import
4. 跑测试
5. commit

### 5.3 Commit规范

`
feat: add video frame extraction tool
feat: add search agent with three-path strategy
refactor: extract prompt building to AgentState method
style: align section headers with project convention
test: add unit tests for URL translation
`

---

## 六、环境配置

`yaml
# config.yaml — 开发/生产切换
model:
  mode: dev  # dev | prod
  dev:
    base_url: https://api.openai.com/v1
    llm_model: gpt-4o
  prod:
    base_url: http://localhost:8000/v1
    llm_model: Qwen3-VL-8B-Instruct
`

**运行方式：**
`powershell
="src"
& C:\working\myproj\vsa-agent\.conda-env\python.exe -m pytest tests/unit/test_config.py -v
`

---

> 本文档随项目演进持续更新。每次新增模块时更新"当前项目状态"表。
