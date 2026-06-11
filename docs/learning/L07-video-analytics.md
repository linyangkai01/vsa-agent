# L07: Video Analytics — 事件分析层

## 1. 模块在业务流中的位置

Video Analytics 是 VSA Agent 的**事件分析层**，位于搜索和 Agent 编排之下，提供结构化的视频事件分析能力。它定义了与 Elasticsearch 等后端交互的接口和查询构建逻辑。

`
Agents / Tools
    ↓
┌──────────────────────┐
│  Video Analytics     │  ← 本课
│  ┌────────────────┐  │
│  │ interface.py   │  │  ← ABC 抽象接口
│  │ query_builders │  │  ← ES 查询构建
│  │ tools.py       │  │  ← 高级分析工具
│  │ utils.py       │  │  ← 时间/事件工具
│  │ nvschema.py    │  │  ← 数据模型 (L02)
│  └────────────────┘  │
└──────────────────────┘
    ↓
Elasticsearch / 后端存储
`

**上下游关系：**
- 上游：	ools/search.py（搜索工具）、gents/（Agent 编排）
- 下游：Elasticsearch（或其他后端存储）

---

## 2. 模块设计理念

### 2.1 分层设计

Video Analytics 模块内部按职责分为五个子模块：

| 文件 | 职责 | 模式 |
|------|------|------|
| 
vschema.py | 数据模型定义（Incident, Location, Place） | 纯数据 |
| interface.py | 抽象接口定义 | ABC 模式 |
| query_builders.py | ES 查询构建 | Builder 模式 |
| 	ools.py | 高级分析工具函数 | 工具函数 |
| utils.py | 时间/事件处理工具 | 工具函数 |

### 2.2 设计要点

1. **抽象接口（ABC）**：VideoAnalyticsInterface 定义了三个核心方法（search_incidents、get_frames、health_check），允许不同的后端实现（ES、Mock、其他）。
2. **ES 查询构建器**：query_builders.py 提供三个查询构建函数，封装 Elasticsearch 查询 DSL，返回标准 ES 查询字典。
3. **时间桶分析**：create_time_buckets() 将时间线分段，nalyze_incident_timeline() 在每个桶内统计事件分布，便于生成时间线报告。
4. **事件合并**：merge_overlapping_events() 将时间上重叠的事件合并，避免重复统计。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **Python bc** | 抽象接口定义 |
| **Elasticsearch Query DSL** | 查询构建（字典格式） |
| **Python dataclasses** | 数据模型 |

---

## 4. 数据模型与接口设计

### 4.1 抽象接口 (interface.py)

`python
class VideoAnalyticsInterface(ABC):
    @abstractmethod
    async def search_incidents(
        self,
        query: str,
        filters: dict[str, Any] | None = None,
        time_range: tuple[float, float] | None = None,
        top_k: int = 10,
    ) -> list[Incident]:
        """搜索匹配的事件。"""

    @abstractmethod
    async def get_frames(
        self,
        sensor_id: str,
        time_range: tuple[float, float],
        max_frames: int = 50,
    ) -> list[str]:
        """获取传感器在时间范围内的帧。"""

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """检查后端健康状态。"""
`

### 4.2 ES 查询构建 (query_builders.py)

`python
def build_incident_query(
    query: str,
    filters: dict[str, Any] | None = None,
    time_range: tuple[float, float] | None = None,
    top_k: int = 10,
) -> dict[str, Any]:
    """构建事件搜索 ES 查询。
    使用 match 查询 + fuzziness 模糊匹配 + 可选过滤器 + 时间范围。
    """

def build_frames_query(
    sensor_id: str,
    time_range: tuple[float, float],
    top_k: int = 50,
) -> dict[str, Any]:
    """构建帧检索 ES 查询。
    使用 term 查询传感器 ID + range 时间范围。
    """

def build_behavior_query(
    behavior_type: str,
    confidence_min: float = 0.5,
    time_range: tuple[float, float] | None = None,
    top_k: int = 20,
) -> dict[str, Any]:
    """构建行为搜索 ES 查询。
    使用 term 查询行为类型 + range 置信度阈值。
    """
`

### 4.3 分析工具 (	ools.py)

`python
async def analyze_incident_timeline(
    incidents: list[Incident],
    bucket_duration_sec: float = 60.0,
) -> list[dict[str, Any]]:
    """分析事件时间线，按时间桶分组统计。
    返回每个桶的时间范围、事件数、严重程度分布。
    """

async def summarize_incidents(
    incidents: list[Incident],
    max_incidents: int = 20,
) -> str:
    """生成事件文本摘要，按置信度排序。"""
`

### 4.4 工具函数 (utils.py)

`python
def create_time_buckets(
    start_sec: float,
    end_sec: float,
    bucket_duration_sec: float = 60.0,
) -> list[tuple[float, float]]:
    """将时间范围分割为均匀的时间桶。"""

def check_event_overlap(
    event_a: tuple[float, float],
    event_b: tuple[float, float],
    threshold_sec: float = 0.0,
) -> bool:
    """检查两个事件是否在时间上重叠。"""

def merge_overlapping_events(
    events: list[tuple[float, float, Any]],
    threshold_sec: float = 0.0,
) -> list[tuple[float, float, list[Any]]]:
    """合并重叠事件为连续时间范围。"""
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/video_analytics/test_interface.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestVideoAnalyticsInterface | 	est_abstract_class_cannot_instantiate | 抽象类不能直接实例化 |
| TestVideoAnalyticsInterface | 	est_concrete_implementation | 实现类可正常实例化 |

### 测试文件：	ests/unit/video_analytics/test_query_builders.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestBuildIncidentQuery | 	est_basic | 基本查询结构正确 |
| TestBuildIncidentQuery | 	est_with_filters | 带过滤器和时间范围的查询 |
| TestBuildFramesQuery | 	est_basic | 帧查询结构正确 |
| TestBuildBehaviorQuery | 	est_basic | 行为查询结构正确 |

### 测试文件：	ests/unit/video_analytics/test_tools.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestAnalyzeIncidentTimeline | 	est_empty_incidents | 空事件列表返回空 |
| TestAnalyzeIncidentTimeline | 	est_single_incident | 单个事件分析 |
| TestSummarizeIncidents | 	est_empty | 空事件返回 "No incidents" |
| TestSummarizeIncidents | 	est_with_incidents | 事件摘要包含描述 |

### 测试文件：	ests/unit/video_analytics/test_utils.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestCreateTimeBuckets | 	est_basic | 10 秒桶分割 100 秒 = 10 个桶 |
| TestCreateTimeBuckets | 	est_single_bucket | 不足一个桶时返回一个桶 |
| TestCreateTimeBuckets | 	est_zero_duration | 零时长返回空 |
| TestCheckEventOverlap | 	est_overlapping | 重叠返回 True |
| TestCheckEventOverlap | 	est_non_overlapping | 不重叠返回 False |
| TestCheckEventOverlap | 	est_adjacent_no_overlap | 相邻（阈值=0）视为重叠 |
| TestCheckEventOverlap | 	est_with_threshold | 带阈值检查 |
| TestMergeOverlappingEvents | 	est_merge_overlapping | 重叠事件合并 |
| TestMergeOverlappingEvents | 	est_no_overlap | 不重叠不合并 |
| TestMergeOverlappingEvents | 	est_empty | 空列表返回空 |

---

## 6. 动手练习

### 练习 1：理解 ES 查询

阅读 uild_incident_query() 的代码，回答：
1. 查询使用 ES 的哪个查询类型（match / term / range）？
2. uzziness: "AUTO" 的作用是什么？
3. 如何添加一个 severity: "critical" 的过滤器？

### 练习 2：实现自定义后端

假设需要实现一个 PostgreSQL 后端的 VideoAnalyticsInterface：
1. 需要新建什么文件？
2. 需要实现哪三个方法？
3. 如何将 ES 查询转换为 SQL 查询？

### 练习 3：理解时间桶分析

回答以下问题：
1. 如果事件时间范围是 0-120 秒，ucket_duration_sec=30，会生成几个桶？
2. check_event_overlap() 的 	hreshold_sec 参数在什么场景下有用？
3. merge_overlapping_events() 返回的列表长度和输入列表长度有什么关系？

---

> **下一步**：学习 [L08: Postprocessing — 输出验证](L08-postprocessing.md)
