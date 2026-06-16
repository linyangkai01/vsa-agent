# L09: API + Embed — 外围层

## 1. 模块在业务流中的位置

API 和 Embed 是 VSA Agent 的**外围层**，分别负责对外暴露 HTTP 接口和对内提供向量嵌入能力。

`
┌─────────────────────────────────┐
│          API (FastAPI)          │  ← 对外接口
│  /health  /api/chat  /search/*  │
└──────────────┬──────────────────┘
               │
               ↓
┌─────────────────────────────────┐
│          Top Agent DAG          │
└─────────────────────────────────┘
               │
               ↓
┌─────────────────────────────────┐
│  Embed (向量嵌入)                │  ← 内部能力
│  EmbedClient / CosmosEmbedClient│
└─────────────────────────────────┘
`

**上下游关系：**
- API 上游：外部客户端（浏览器、其他服务）
- API 下游：gents/top_agent.py（核心 Agent DAG）
- Embed 上游：	ools/embed_search.py（向量搜索）
- Embed 下游：sentence-transformers 模型

---

## 2. 模块设计理念

### 2.1 API 层

API 层使用 **FastAPI** 框架，提供以下端点：

| 端点 | 方法 | 功能 |
|------|------|------|
| /health | GET | 健康检查 |
| /api/chat | POST | 聊天接口（SSE 流式响应） |
| /api/search/ingest | POST | 视频索引提交 |
| /api/video/upload-url | POST | 视频上传预签名 URL |

**设计要点：**

1. **SSE 流式响应**：/api/chat 使用 Server-Sent Events（SSE）流式返回 Agent 的思考过程、工具调用和最终回复，提供实时交互体验。
2. **LangGraph 集成**：每次请求动态编译 LangGraph DAG，通过 graph.astream() 获取流式输出块。
3. **简化实现**：ideo_search_ingest 和 ideo_upload_url 为简化版，返回 mock 数据，生产环境需要集成 Elasticsearch 和 S3/MinIO。

### 2.2 Embed 层

Embed 层使用 **抽象基类 + 具体实现** 的模式：

- **EmbedClient**（embed.py）：抽象基类，定义 embed()、embed_query()、dimension 接口
- **CosmosEmbedClient**（cosmos_embed.py）：具体实现，使用 sentence-transformers 本地生成嵌入向量

**设计要点：**

1. **延迟加载**：_ensure_model() 在首次调用时加载模型，避免初始化时加载所有模型。
2. **降级策略**：如果 sentence-transformers 未安装，自动降级为 mock 嵌入（基于 MD5 哈希的确定性向量）。
3. **标准化**：mock 嵌入向量经过 L2 归一化，确保余弦相似度计算正确。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **FastAPI** | HTTP 框架 |
| **SSE (Server-Sent Events)** | 流式响应 |
| **LangGraph stream** | Agent DAG 流式执行 |
| **sentence-transformers** | 文本嵌入生成 |
| **Python hashlib / math** | Mock 嵌入生成 |

---

## 4. 数据模型与接口设计

### 4.1 API 接口

`python
# routes.py
class ChatRequest(BaseModel):
    message: str

app = FastAPI(title='vsa-agent', description='Video Safety Analysis Agent')

@app.get('/health')
async def health():
    return {'status': 'ok', 'service': 'vsa-agent'}

@app.post('/api/chat')
async def chat(req: ChatRequest):
    """SSE 流式聊天接口。
    返回事件流：data: {"type": "thought", "content": "..."}
              data: {"type": "tool_call", "content": "..."}
              data: {"type": "final", "content": "..."}
              data: [DONE]
    """

# video_search_ingest.py
@router.post("/search/ingest")
async def video_search_ingest(video_id: str, metadata: dict | None = None):
    """提交视频进行搜索索引。"""

# video_upload_url.py
@router.post("/video/upload-url")
async def get_video_upload_url(filename: str):
    """获取视频上传的预签名 URL。"""
`

### 4.2 Embed 接口

`python
# embed.py
class EmbedClient(ABC):
    @abstractmethod
    async def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        """生成文本嵌入向量。"""

    @abstractmethod
    async def embed_query(self, query: str) -> list[float]:
        """生成单个查询的嵌入向量。"""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """返回嵌入向量维度。"""

# cosmos_embed.py
class CosmosEmbedClient(EmbedClient):
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """使用 sentence-transformers 的嵌入客户端。"""

    @property
    def dimension(self) -> int:
        return self._dimension  # 默认 384

    async def embed(self, inputs: Sequence[str]) -> list[list[float]]:
        """生成嵌入向量。模型未加载时降级为 mock。"""

    async def embed_query(self, query: str) -> list[float]:
        """生成查询嵌入向量。"""
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/api/test_routes.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestChatEndpoint | 	est_router_imports | FastAPI app 可导入 |

### 测试文件：	ests/unit/api/test_health.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestHealthEndpoint | 	est_health_imports | Health app 可导入 |

### 测试文件：	ests/unit/embed/test_embed.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestEmbedClient | 	est_abstract_class_cannot_instantiate | 抽象类不能直接实例化 |
| TestEmbedClient | 	est_concrete_implementation | 实现类可正常实例化 |

### 测试文件：	ests/unit/embed/test_cosmos_embed.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestCosmosEmbedClient | 	est_initialization | 可初始化 |
| TestCosmosEmbedClient | 	est_embed_query_returns_vector | 查询嵌入返回向量 |
| TestCosmosEmbedClient | 	est_embed_returns_vectors | 批量嵌入返回向量列表 |
| TestCosmosEmbedClient | 	est_empty_input | 空输入返回空列表 |

---

## 6. 动手练习

### 练习 1：理解 SSE 流式响应

阅读 outes.py 中 /api/chat 的实现，回答：
1. 响应使用什么 Content-Type？
2. 客户端如何判断流式响应结束？
3. 每个事件块包含什么字段？

### 练习 2：添加新的 API 端点

假设需要添加一个 /api/search 端点，接收查询并返回搜索结果：
1. 需要新建什么文件？
2. 请求和响应的 Pydantic 模型是什么？
3. 如何调用 search_agent_tool？

### 练习 3：理解 Embed 降级策略

回答以下问题：
1. 如果 sentence-transformers 未安装，CosmosEmbedClient 会怎样？
2. Mock 嵌入是如何生成的？为什么需要 L2 归一化？
3. ll-MiniLM-L6-v2 模型的嵌入维度是多少？

---

> **所有课程已完成！** 返回 [INDEX.md](INDEX.md) 查看总索引。
