# L05: Video Understanding — VLM 视频分析

## 1. 模块在业务流中的位置

Video Understanding 是 VSA Agent 的**视频分析核心**，负责调用 VLM（Vision-Language Model）对视频帧进行理解和描述。它是连接视频文件和 LLM 分析的关键桥梁。

`
用户查询 → Top Agent → video_understanding_tool
                            ↓
                    ┌─────────────────┐
                    │ Video Understanding│  ← 本课
                    └─────────────────┘
                    ↙               ↘
             帧提取 (OpenCV)      VLM 分析
              ↓                      ↓
          frame_store            Model Adapter
`

**上下游关系：**
- 上游：gents/top_agent.py（顶层 Agent 调用）
- 下游：	ools/frame_extract.py（帧提取）、	ools/frame_store.py（帧存储）、model_adapter/（VLM 调用）

---

## 2. 模块设计理念

### 2.1 智能分块策略（Chunking Strategy）

系统根据视频时长自动选择分析策略：

`
视频输入
    │
    ├─ 短视频 (≤40s) ──────────────────────────┐
    │   1. 提取最多 24 帧（均匀采样）             │
    │   2. 一次性发送给 VLM                      │
    │   3. 返回单段描述                          │
    │                                            │
    └─ 长视频 (>40s) ───────────────────────────┘
      1. 按 CHUNK_DURATION_SEC 分块
      2. 每块提取最多 10 帧
      3. 逐块发送给 VLM
      4. 聚合所有块的描述为完整报告
`

### 2.2 设计要点

1. **Multimodal VLM（Design Pattern #2）**：将视频帧编码为 base64 JPEG，通过 HumanMessage 的多模态内容格式发送给 VLM。
2. **Intent-Aware Prompting（Design Pattern #11）**：System Prompt 明确指示 VLM 关注用户查询相关的细节（环境、人物、物体、行为）。
3. **帧存储共享（Frame Store）**：rame_extract 将帧存入内存中的 _frame_store，ideo_understanding 通过 rame_key 读取，避免帧数据在 LLM 消息循环中传递。
4. **推理内容解析**：_parse_thinking_from_content() 使用 utils/reasoning_parsing.py 提取 VLM 的推理过程和最终答案。
5. **依赖注入**：model_adapter 参数支持依赖注入，便于测试时 mock VLM 调用。

---

## 3. 涉及的技术栈

| 技术 | 用途 |
|------|------|
| **OpenCV (cv2)** | 视频读取、帧提取、JPEG 编码 |
| **LangChain HumanMessage / SystemMessage** | 多模态消息构建 |
| **Base64** | 帧图像编码 |
| **Python math** | 帧索引计算 |
| **UUID** | 帧存储引用键 |

---

## 4. 数据模型与接口设计

### 4.1 数据模型

`python
class VideoUnderstandingInput(BaseModel):
    """视频理解输入"""
    sensor_id: str = ""
    start_timestamp: str = ""
    end_timestamp: str = ""
    user_prompt: str = ""
    video_path: str = ""
    max_frames: int = 10

class VideoUnderstandingConfig(BaseModel):
    """视频理解配置"""
    max_fps: float = 2.0           # 最大帧率
    min_pixels: int = 224 * 224    # 最小分辨率
    max_pixels: int = 1280 * 720   # 最大分辨率
    reasoning_effort: str = "medium"
    filter_thinking: bool = True
    max_retries: int = 3           # VLM 最大重试次数
`

### 4.2 核心函数签名

`python
@register_tool("video_understanding", description="...")
async def video_understanding_tool(
    video_path: str = "",
    query: str = "",
    model_adapter=None,
    frames: list[str] | None = None,
) -> str:
    """分析视频文件。自动处理短/长视频的分块策略。"""

def _extract_frames(
    video_path: str,
    max_frames: int,
    start_timestamp: float = 0.0,
    end_timestamp: float | None = None,
) -> tuple[list[str], float, float, int]:
    """从视频中提取均匀采样的帧，返回 (base64_frames, duration_sec, fps, total_frames)。"""

async def _analyze_frames(
    frames: list[str],
    query: str,
    model_adapter=None,
) -> str:
    """将帧发送给 VLM 进行分析。"""

async def _analyze_chunked(
    video_path: str,
    query: str,
    duration_sec: float,
    model_adapter=None,
) -> str:
    """长视频分块分析：逐块提取帧 → VLM → 聚合报告。"""

def _build_vlm_messages(
    frames: list[str],
    query: str,
    system_prompt: str | None = None,
) -> list[BaseMessage]:
    """构建 VLM 多模态消息（SystemMessage + HumanMessage 含图片）。"""

def _parse_thinking_from_content(content: str) -> tuple[str | None, str]:
    """解析 VLM 响应，分离推理过程和最终答案。"""
`

### 4.3 Frame Store 接口 (	ools/frame_store.py)

`python
def store_frames(frames: list[str], metadata: dict) -> str:
    """存储帧并返回引用 key。"""

def get_frames(key: str) -> list[str] | None:
    """通过 key 获取帧。"""

def get_metadata(key: str) -> dict | None:
    """通过 key 获取元数据。"""

def clear_key(key: str) -> None:
    """删除指定 key 的帧。"""

def clear_all() -> None:
    """清空所有帧。"""
`

---

## 5. 测试如何验证

### 测试文件：	ests/unit/tools/test_video_understanding.py

| 测试类 | 测试方法 | 验证内容 |
|--------|----------|----------|
| TestVideoUnderstandingInput | 	est_defaults | 默认 max_frames=10 |
| TestVideoUnderstandingConfig | 	est_defaults | 默认 max_fps=2.0, max_retries=3 |
| TestBuildVlmMessages | 	est_builds_messages | 正确构建 system + human 消息 |
| TestParseThinkingFromContent | 	est_no_thinking | 无推理标签时直接返回内容 |
| TestParseThinkingFromContent | 	est_with_thinking_tags | 正确提取 <answer> 标签内容 |
| TestParseThinkingFromContent | 	est_empty_string | 空字符串处理 |

---

## 6. 动手练习

### 练习 1：理解分块策略

阅读 ideo_understanding.py 中的 LONG_VIDEO_THRESHOLD_SEC 和 CHUNK_DURATION_SEC 常量，回答：
1. 一个 60 秒的视频会被分多少块？
2. 每块提取多少帧？总共发送给 VLM 多少帧？
3. 如果 VLM 的上下文窗口限制为 20 张图片，需要修改哪个参数？

### 练习 2：实现自定义帧选择策略

假设需要实现"关键帧检测"策略（只提取场景切换时的帧），而不是均匀采样：
1. 需要修改 _extract_frames() 的什么逻辑？
2. 如何利用 OpenCV 的 cv2.Canny() 边缘检测来判断帧变化？
3. 写出伪代码框架。

### 练习 3：理解 Frame Store 模式

回答以下问题：
1. 为什么需要 rame_store 而不是直接在 LLM 消息中传递帧？
2. rame_key 是如何生成的？
3. 帧数据何时被清理？是否存在内存泄漏风险？

---

> **下一步**：学习 [L06: Agents — 业务流程编排](L06-agents.md)
