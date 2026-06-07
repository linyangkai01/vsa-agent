'''Prompt constants used by VSA agent tools.'''

# ===== System Prompts =====

DEFAULT_SYSTEM_PROMPT = (
    'You are an industrial safety video analysis agent. '
    'Use tools to analyze videos and generate safety reports. '
    'Respond directly when no tools are needed.'
)

# ===== Safety Inspection Prompts =====

SAFETY_ROUTINE_INSPECTION = (
    '你是工业安全巡检系统。检查视频中是否存在：'
    '1. 未佩戴安全帽的人员\n'
    '2. 未穿防护服的人员\n'
    '3. 危险区域（标记为红区）的闯入行为\n'
    '对每个违规，记录：时间戳、违规类型、人员描述、位置'
)

SAFETY_INCIDENT_INVESTIGATION = (
    '你是工业安全调查系统。还原事件发生过程：'
    '1. 识别事件发生前的异常行为\n'
    '2. 追踪涉事人员的行动轨迹\n'
    '3. 分析可能的触发因素\n'
    '按时间顺序描述完整事件链，标注每个阶段的关键证据'
)

# ===== VLM Prompt Templates =====

VLM_FORMAT_INSTRUCTION = (
    "DON'T MAKE UP ANYTHING THAT NOT FROM THE VIDEO. "
    "DON'T HALLUCINATE ANYTHING. "
    "Start and end each caption with the timestamp in pts format, "
    'for example, " <10.5> event_description <11.5> ".'
)
