# 选中录播片段确定性路由

## 背景

原版 UI 会把搜索结果中的 `assetId`、`segmentId` 和片段时间范围作为上下文提交给
`/chat/stream`。API 已通过 SQLite repository 和受控 asset store 解析这些标识，并只把
本地路径保存在 `AgentState.local_video_context`，不会把路径或标识发送给远程 LLM。

真实 `qwen-turbo` 验收发现，仅依赖 system prompt 说明不足以保证工具选择。模型在已有
服务端验证片段时仍可能调用通用 `find_video`，导致没有执行本地
`video_understanding`，trace 门禁因缺少本地视频理解证据而正确失败。

## 路由契约

1. API 只有在通过 repository 和 asset store 验证录播片段后，才设置显式
   `selected_recorded_video` 状态位；普通 `local_video_context` 不触发该路由。
2. TopAgent 仍调用当前 profile 的真实远程 LLM，使 provider、认证和工具调用接口保持
   在正式链路内。
3. 首轮模型响应必须由编排层规范化为且仅为一次 `video_understanding` 调用：
   - 模型正确选择一次该工具时保留调用；
   - 模型直接回答、选择其他工具或产生多个调用时，替换为一个运行时生成的调用；
   - trace 只记录安全的路由结果，不记录本地路径、片段标识或模型原始正文。
4. 工具的 `video_path`、`start_timestamp` 和 `end_timestamp` 始终由
   `AgentState.local_video_context` 覆盖。模型不能选择或覆盖本地资源。
5. 用户问题由当前消息补齐；模型提供非空 `query` 时可以保留，但不能阻止本地参数注入。
6. 普通聊天以及没有 `local_video_context` 的视频请求保持现有模型驱动工具选择行为。

## Provider 探针契约

当前 profile 的本地 vLLM 声明 `api_key_required: false`。readiness 探针必须允许这种
loopback provider 在省略 Authorization 时完成 OpenAI-compatible 请求，不能把无密钥
本地服务误判为配置错误。需要密钥的远程 provider 仍必须 fail-closed。
`ChatOpenAI` 客户端自身要求非空 key 时，vLLM 专用适配器使用固定非敏感占位值满足
客户端构造；该值不是凭据，不会启用服务端鉴权，也不得用于远程 provider。

## 验收标准

- 单元测试覆盖模型误选 `find_video`、模型直接回答、正确选择
  `video_understanding`、本地路径与时间覆盖、普通聊天不变。
- provider probe 同时覆盖无密钥本地 vLLM 和缺失远程 key 两种情况。
- Ubuntu 上 `qwen-turbo`、`text-embedding-v4` 和 24 帧本地 vLLM 请求成功。
- 真实业务 quick 六用例通过上传、Worker、ES 搜索、缩略图、Range 播放、选中片段问答、
  trace 一致性和资产删除。
- 日志和 trace 不包含密钥、本地绝对路径、原始帧、远程 prompt 或模型正文。
