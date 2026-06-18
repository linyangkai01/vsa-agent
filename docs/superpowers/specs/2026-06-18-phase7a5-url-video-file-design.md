# Phase 7A5 源路径翻译与视频文件工具对齐设计

> 范围：`utils/url_translation.py`、`utils/video_file.py`、`tools/video_understanding.py`
> 日期：2026-06-18
> 目标：补齐视频源路径翻译与本地视频文件探测工具，让远程/挂载/本地三类来源在共享工具层获得更稳定的统一处理。

## 一、背景

到 Phase 7A4 为止，Phase 7 已经完成了四段基础设施补齐：

1. A1：prompt / reasoning / async 生命周期
2. A2：VSS 数据模型 / 时间转换 / 选帧
3. A3：retry / model adapter
4. A4：parser / markdown_parser

继续往下，最贴近真实主链、同时又还留有基础设施缺口的一组模块，是：

- `utils/url_translation.py`
- `utils/video_file.py`（当前缺失）
- `tools/video_understanding.py` 中对视频源路径的消费逻辑

这组模块的重要性在于，它不只是“多一个工具文件”，而是直接决定：

- 本地路径、`file://`、S3/MinIO、HTTP clip、RTSP clip 之间如何被统一处理
- `video_understanding` 在 translated/source_mode 场景下能否更稳定地消费路径
- 后续 VST 更真实接入时，我们是否已经有了合理的本地文件工具层

## 二、现状问题

### 1. `url_translation.py` 已存在，但仍偏轻量

当前 `src/vsa_agent/utils/url_translation.py` 已经具备：

- `translate_url(...)`
- `is_remote_url(...)`

但它还有几个明显缺口：

1. 路径语义和“文件是否本地可访问”没有完全分开
2. Windows / POSIX / `file://` 的规范化能力还不够清晰
3. `video_understanding._prepare_video_path()` 仍然承担了过多“路径是否可接受”的业务判断

换句话说，路径翻译工具已经有了雏形，但还没发展成一层稳定的 shared file-source utilities。

### 2. `video_file.py` 还不存在

在原版架构里，`video_file.py` 属于 utils 的一部分，用于承接视频文件操作。

当前仓库还没有这个文件，这导致一些本来应属于公共文件层的行为只能散落在调用方里，例如：

- 是否本地存在
- 是否是本地文件候选
- 规范化本地路径

### 3. `video_understanding.py` 仍然混合了“路径翻译”和“文件可达性判断”

当前 `_prepare_video_path(...)` 同时做了：

- 远程 URL 检测
- translated mode 翻译
- RTSP/HTTP 远程 clip 特判
- 翻译后仍远程时的拒绝逻辑

这本身没错，但职责边界比较重。

更理想的状态是：

- `url_translation.py` 负责“如何翻译”
- `video_file.py` 负责“翻译后的东西是否可作为本地文件消费”
- `video_understanding.py` 只保留少量业务特判

## 三、设计目标

Phase 7A5 的目标如下：

1. 补强 `url_translation.py` 的路径翻译与规范化语义
2. 新增 `video_file.py`，收口本地视频文件候选判断
3. 让 `video_understanding.py` 改用共享 file-source 工具，而不是自己承担全部判断
4. 保持现有外部接口与大部分行为不变
5. 对 translated/source_mode/RTSP clip 场景继续保持兼容

## 四、候选方案

### 方案 A：最小共享文件源工具层（推荐）

做法：

- 补强 `url_translation.py`
- 新增 `video_file.py`
- `video_understanding.py` 仅改 `_prepare_video_path(...)` 这条链

优点：

- 风险小
- 能立刻改善主链职责边界
- 与当前代码结构最兼容

缺点：

- 不会一次性覆盖所有未来 VST 文件场景

### 方案 B：把 VST clip / 本地挂载 / 下载缓存全都统一进一个大文件服务层

做法：

- 新增更大的 source resolver / file manager 层

优点：

- 长期更统一

缺点：

- 对当前阶段过重
- 会把 A5 推成较大的业务基础设施重构

### 方案 C：只增强 `url_translation.py`，不新增 `video_file.py`

优点：

- 改动最少

缺点：

- 仍然缺失独立视频文件工具层
- `_prepare_video_path()` 的职责边界问题不会真正改善

## 五、最终选择

本阶段采用 **方案 A：最小共享文件源工具层**。

理由：

- 能同时补齐原版中还缺的 `video_file.py`
- 直接服务 `video_understanding` 主链
- 不会把 Phase 7 拉成过大的 VST 重构

## 六、模块设计

### 1. `utils/url_translation.py`

本阶段建议保留现有公开函数名，但增强语义：

- `translate_url(url, target_base=None) -> str`
  - 本地路径：规范化后返回
  - `file://`：转本地路径，若给了 `target_base` 则映射到目标目录
  - S3/MinIO：按 bucket/key 拼到目标挂载目录
  - HTTP/HTTPS/RTSP：默认保留原值

- `is_remote_url(url) -> bool`
  - 更稳地区分 Windows drive path、本地相对路径、URI

可考虑新增：

- `normalize_local_path(path: str) -> str`
  - 统一斜杠与本地路径表达

### 2. `utils/video_file.py`

建议新增最小能力：

- `is_local_video_candidate(path: str) -> bool`
  - 是否是本地文件候选，而不是远程 URL

- `ensure_local_video_path(path: str) -> str`
  - 对明显远程路径直接报错
  - 对本地路径做规范化后返回

注意：

- 本阶段不负责探测编解码信息
- 不负责视频元数据读取
- 不负责下载远程文件

### 3. `tools/video_understanding.py`

接入方式：

- `_prepare_video_path(...)` 改为依赖共享 `translate_url()` + `ensure_local_video_path()`
- 仅保留 RTSP/HTTP clip 这类业务特判

这样职责会变成：

1. 如果需要翻译，调用 `translate_url()`
2. 如果是 RTSP 场景且仍为远程 clip，则按现有逻辑允许
3. 其余场景通过 `ensure_local_video_path()` 验证

## 七、测试策略

### 1. `tests/unit/utils/test_url_translation.py`

补强覆盖：

- `file://` 规范化
- Windows drive path 仍被识别为本地
- `rtsp://` / `https://` 被识别为远程
- S3/MinIO 拼接 target_base 的边界

### 2. 新增 `tests/unit/utils/test_video_file.py`

覆盖：

- 本地绝对路径
- Windows 风格路径
- 远程 URL 拒绝
- 空字符串边界

### 3. `tests/unit/tools/test_video_understanding.py`

继续锁定：

- translated remote source -> local path
- translated 后仍远程 -> `video_file` 场景报错
- RTSP source 允许远程 clip
- `_prepare_video_path()` 已接入共享工具层

## 八、非目标

本阶段不做：

- 远程下载
- 视频元数据探测工具层
- VST clip 持久化缓存
- file mapping / cache registry

## 九、验收标准

1. `url_translation.py` 行为更稳定
2. 新增 `video_file.py`
3. `video_understanding._prepare_video_path()` 改用共享文件源工具
4. A5 相关单测全部通过
5. 唯一总计划文档同步记录 A5 状态

