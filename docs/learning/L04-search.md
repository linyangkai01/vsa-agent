# L04: Search — 核心搜索（三路径路由）

## 1. 模块在业务流中的位置

Search 是 VSA Agent 的**核心搜索引擎**，负责根据自然语言查询找到匹配的视频片段。它位于 Agent 编排层和底层数据存储之间，是系统最关键的业务逻辑模块。

`
用户查询 → Top Agent → search_agent
                          ↓
                   ┌──────────────┐
                   │  Search 引擎  │  ← 本课
                   └──────────────┘
                   ↙       ↓       ↘
             Embed搜索  属性搜索   融合搜索
                ↓          ↓
           向量存储     属性索引
`

**上下游关系：**
- 上游：gents/search_agent.py（搜索 Agent 调用）、gents/top_agent.py（顶层 Agent 路由）
- 下游：	ools/vector_store.py（向量存储）、	ools/embed_search.py（向量搜索）、	ools/attribute_search.py（属性搜索）

---

## 2. 模块设计理念

### 2.1 Three-Path Search Strategy（三路径搜索策略）

这是系统的核心设计模式（Design Pattern #13）。搜索根据查询特征自动选择三条路径之一：

`
用户查询
    │
    ├─ 查询分解 (decompose_query)
    │   ├─ attributes: [...]      ← 提取属性关键词
    │   └─ has_action: True/False  ← 判断是否包含动作描述
    │
    ├─ Path 1: 纯属性搜索 ──────────────────────────────┐
    │   has_action=False AND attributes 非空             │
    │   例："person in red jacket"（静态属性匹配）        │
    │                                                    │
    ├─ Path 2: 纯向量搜索 ──────────────────────────────┤
    │   attributes 为空                                  │
    │   例："someone walking near the loading dock"      │
    │                                                    │
    └─ Path 3: 融合搜索 ────────────────────────────────┘
       has_action=True AND attributes 非空
       例："a person in a red jacket is running"
       → 向量搜索 + 属性搜索 → 融合排序
`

### 2.2 查询分解（Query Decomposition）

decompose_query() 使用 LLM 将自然语言查询分解为结构化参数：

- **query**：主搜索描述（保留语义）
- **ideo_sources**：指定视频源
- **source_type**：ideo_file 或 
tsp
- **	imestamp_start/end**：时间范围
- **ttributes**：提取的视觉属性列表
- **has_action**：是否包含动作/事件描述
- **	op_k**：返回结果数量

### 2.3 融合算法（Fusion Methods）

当同时使用向量搜索和属性搜索时，支持三种融合策略：

| 方法 | 说明 | 适用场景 |
|------|------|----------|
| **Weighted Linear** | score = w_embed * embed_score + w_attribute * attr_score | 需要精确控制权重 |
| **RRF (Reciprocal Rank Fusion)** | score = 1/(rank_embed + k) + w * normalised_attr_score | 对排名敏感，忽略分数绝对值 |
| **RRF with Attribute Rank** | score = 1/(rank_embed + k) + w * 1/(rank_attribute + k) | 属性匹配更重要时 |

### 2.4 融合算法实现（Phase A）

Phase A 新增了完整的融合算法实现，位于 	ools/search.py 中：

- **ttribute_result_to_search_result()** — 将 AttributeSearchResult 转换为 SearchResult，使用 rame_score（优先）或 ehavior_score 作为相似度分数。
- **_apply_weighted_linear_fusion()** — 加权线性融合：w_embed * embed_score + w_attribute * normalised_attribute_score。
- **_apply_rrf_fusion()** — 倒数秩融合：1/(rank_embed + k) + w * normalised_attribute_score。
- **_apply_rrf_fusion_with_attribute_rank()** — 双秩 RRF：同时使用 embed 排名和 attribute 排名计算 RRF 分数。
- **usion_search_rerank()** — 顶层融合入口：对每个 embed 结果运行属性搜索，计算归一化属性分数，然后应用指定的融合方法。
- **_run_attribute_only_search()** — 纯属性搜索路径：当查询只有属性无动作时使用。
- **execute_core_search_wrapper()** — 非流式包装器（Phase B）：将 execute_core_search 的 AsyncGenerator 输出收集为单个 SearchOutput。

### 2.5 属性搜索增强（Phase B）

ttribute_search.py 新增了多属性搜索支持：

- **search_single_attribute()** — 搜索单个属性，返回 AttributeSearchResult 列表。
- **search_attributes()** — 搜索多个属性，遍历每个查询并聚合结果。
- **_fuse_multi_attribute()** — 交集策略：只保留在所有属性中都出现的视频。
- **_append_multi_attribute()** — 并集策略：返回所有唯一视频（每个视频取最高分）。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **Pydantic v2** | 搜索数据模型（DecomposedQuery, SearchResult, SearchOutput） |
| **LangChain ChatOpenAI** | 查询分解（LLM 调用） |
| **Async/Await** | 异步搜索执行 |
| **AsyncGenerator** | 流式搜索更新 |

---

## 4. 数据模型与接口设计

### 4.1 核心数据模型

`python
class DecomposedQuery(BaseModel):
    """结构化搜索参数"""
    query: str = ""
    video_sources: list[str] = []
    source_type: str = "video_file"
    timestamp_start: str | None = None
    timestamp_end: str | None = None
    attributes: list[str] = []
    has_action: bool | None = None
    top_k: int | None = None
    min_cosine_similarity: float | None = None

class SearchResult(BaseModel):
    """单个搜索结果"""
    video_name: str          # 视频文件名
    description: str         # 内容描述
    start_time: str          # 开始时间 (ISO)
    end_time: str            # 结束时间 (ISO)
    sensor_id: str           # 传感器 ID
    screenshot_url: str = "" # 截图 URL
    similarity: float        # 余弦相似度 (0.0-1.0)
    object_ids: list[str] = []  # 跟踪对象 ID

class SearchOutput(BaseModel):
    """搜索结果容器"""
    data: list[SearchResult] = []

class SearchConfig(BaseModel):
    """搜索配置"""
    embed_search_tool: str = "embed_search"
    attribute_search_tool: str | None = None
    embed_confidence_threshold: float = 0.2
    agent_mode_llm: str | None = None
    use_attribute_search: bool = False
    default_max_results: int = 10
    fusion_method: str = "rrf"  # weighted_linear / rrf / rrf_with_attribute_rank
    w_embed: float = 0.35
    w_attribute: float = 0.55
    rrf_k: int = 60
    rrf_w: float = 0.5

class SearchInput(BaseModel):
    """搜索输入"""
    query: str                # 搜索查询
    source_type: str = "video_file"
    video_sources: list[str] | None = None
    description: str | None = None
    timestamp_start: str | None = None
    timestamp_end: str | None = None
    top_k: int | None = None
    min_cosine_similarity: float = 0.0  # ?????????
    use_critic: bool = True             # ???? VLM Critic ????
    agent_mode: bool = True
`

### 4.2 核心函数签名

`python
async def execute_core_search_wrapper(
    search_input, embed_search, agent_llm=None, config=None,
    builder=None, attribute_search_fn=None, critic_agent=None,
) -> SearchOutput:
    """????????? generator ??????? SearchOutput?"""


async def execute_core_search(
    search_input: SearchInput,
    embed_search,
    agent_llm=None,
    config: SearchConfig | None = None,
    attribute_search_fn=None,
) -> AsyncGenerator[SearchOutput, None]:
    """核心搜索：三路径路由。以 AsyncGenerator 方式 yield 搜索结果。"""

async def decompose_query(
    query: str,
    llm,
) -> DecomposedQuery:
    """使用 LLM 将自然语言查询分解为结构化参数。"""

def attribute_result_to_search_result(
    attr_result, video_name=None, description="",
) -> SearchResult:
    """? AttributeSearchResult ??? SearchResult?"""


async def fusion_search_rerank(
    embed_results, attributes, attribute_search_fn,
    fusion_method="rrf", rrf_k=60, rrf_w=0.5,
    w_attribute=0.55, w_embed=0.35, source_type="video_file",
) -> list[SearchResult]:
    """?????? embed ??????????????"""


async def _run_attribute_only_search(
    attributes, attribute_search_fn, top_k=10, source_type="video_file",
) -> list[SearchResult]:
    """???????????????? SearchResult?"""


def fuse_results(
    video_data: list[dict],
    fusion_method: str = "rrf",
    w_embed: float = 0.35,
    w_attribute: float = 0.55,
    rrf_k: int = 60,
    rrf_w: float = 0.5,
) -> list[SearchResult]:
    """融合向量搜索和属性搜索的结果。"""

@register_tool("search", description="...")
async def search_tool(
    query: str,
    embed_store=None,
    attr_store=None,
    decomposed_attributes: list[str] | None = None,
    decomposed_has_action: bool | None = None,
    top_k: int = 10,
) -> SearchOutput:
    """已注册的搜索工具：自动选择搜索路径。"""
`

### 4.3 Embed Search 接口 (	ools/embed_search.py)

`python
@register_tool("embed_search", description="...")
async def embed_search_tool(
    query: str,
    store=None,
    top_k: int = 10,
) -> SearchOutput:
    """语义向量搜索：通过文本描述查找视频片段。"""
`

### 4.4 Attribute Search 接口 (	ools/attribute_search.py)

`python
@register_tool("attribute_search", description="...")
async def attribute_search_tool(
    attributes: list[str],
    store=None,
    top_k: int = 5,
) -> SearchOutput:
    """属性搜索：通过视觉属性描述查找视频片段。"""
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/tools/test_search.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestDecomposedQuery | 	est_defaults | 默认值正确 |
| TestDecomposedQuery | 	est_with_values | 自定义值正确设置 |
| TestSearchResult | 	est_required_fields | 必填字段正确 |
| TestSearchOutput | 	est_defaults | 默认 data 为空列表 |
| TestSearchConfig | 	est_defaults | 默认融合方法为 "rrf" |
| TestSearchInput | 	est_required_fields | 必填字段 query |
| TestFusionFunctions | 	est_weighted_linear_fusion | 加权线性融合计算正确 |
| TestFusionFunctions | 	est_rrf_fusion | RRF 融合返回正确结构 |

### 测试文件：	ests/unit/tools/test_embed_search.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestEmbedSearchResultItem | 	est_defaults | 默认值正确 |
| TestEmbedSearchOutput | 	est_defaults | 默认 results 为空 |
| TestQueryInput | 	est_defaults | source_type 默认 "video_file" |
| TestGenerateQueryEmbedding | 	est_with_query_text | 有查询文本时生成向量 |
| TestGenerateQueryEmbedding | 	est_empty_query | 空查询返回空列表 |
| TestProcessSearchHit | 	est_basic_hit | ES 命中转换为 EmbedSearchResultItem |
| TestProcessSearchHit | 	est_below_threshold | 低于阈值的命中被过滤 |

### 测试文件：	ests/unit/tools/test_attribute_search.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestAttributeSearchInput | 	est_required_fields | 必填字段 query |
| TestAttributeSearchMetadata | 	est_required_fields | 必填字段 sensor_id, object_id |
| TestAttributeSearchResult | 	est_required_fields | metadata 字段正确 |
| TestSearchByAttributes | 	est_returns_list | 返回列表 |
| TestDeduplicateByVideoName | 	est_deduplicates | 按 video_name 去重，保留最高分 |

---

## 6. 动手练习

### 练习 1：理解三路径路由

对于以下查询，判断会走哪条搜索路径：
1. "red helmet"（只有属性，无动作）
2. "someone is walking"（只有动作，无属性）
3. "a person in a yellow vest is running near the conveyor belt"（既有属性又有动作）

### 练习 2：实现新的融合方法

假设需要添加一个 max_fusion 方法（取向量分数和属性分数的最大值），请写出：
1. 需要在 search.py 中添加什么代码？
2. 在 use_results() 函数中如何添加新分支？
3. 对应的测试用例应该验证什么？

### 练习 3：理解查询分解

假设用户输入查询："Find a person in a blue hard hat near the loading dock between 2pm and 3pm"

1. 使用 LLM 分解后，ttributes 字段可能包含什么？
2. has_action 的值应该是 True 还是 False？
3. 	imestamp_start 和 	imestamp_end 应该是什么？

---

> **下一步**：学习 [L05: Video Understanding — VLM 视频分析](L05-video-understanding.md)
