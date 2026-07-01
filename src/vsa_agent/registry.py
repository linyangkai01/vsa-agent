from contextlib import contextmanager
from typing import Callable, Any

_TOOLS: dict[str, Callable] = {}

def register_tool(name: str, description: str = ''):
    def decorator(func: Callable) -> Callable:
        _TOOLS[name] = func
        func._tool_name = name
        func._tool_description = description
        return func
    return decorator


@contextmanager
def temporary_tool_override(name: str, func: Callable, description: str = ''):
    original = _TOOLS.get(name)
    original_description = getattr(original, "_tool_description", "") if original else ""
    _TOOLS[name] = func
    func._tool_name = name
    func._tool_description = description
    try:
        yield
    finally:
        if original is None:
            _TOOLS.pop(name, None)
        else:
            _TOOLS[name] = original
            original._tool_name = name
            original._tool_description = original_description


_loaded = False

def _ensure_loaded():
    global _loaded
    if not _loaded:
        from vsa_agent.config import get_config
        import importlib
        cfg = get_config()
        for module_path in cfg.tools.enabled_modules:
            importlib.import_module(module_path)
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
