from typing import Callable, Any

_TOOLS: dict[str, Callable] = {}

def register_tool(name: str, description: str = ''):
    def decorator(func: Callable) -> Callable:
        _TOOLS[name] = func
        func._tool_name = name
        func._tool_description = description
        return func
    return decorator


_loaded = False

def _ensure_loaded():
    global _loaded
    if not _loaded:
        from vsa_agent.tools import register  # noqa: F401
        _loaded = True


class ToolRegistry:
    @classmethod
    def get_all(cls) -> dict[str, Callable]:
        _ensure_loaded()
        return dict(_TOOLS)

    @classmethod
    def get(cls, name: str) -> Callable | None:
        _ensure_loaded()
        return _TOOLS.get(name)

    @classmethod
    def list_tools(cls) -> list[dict[str, str]]:
        _ensure_loaded()
        return [{'name': n, 'description': getattr(f, '_tool_description', '')}
                for n, f in _TOOLS.items()]
