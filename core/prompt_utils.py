"""Prompt 工具模块 — 提供带精准性约束的 prompt 加载函数"""
import os

_ACCURACY_CONSTRAINTS = None


def get_accuracy_constraints() -> str:
    """加载并缓存精准性约束文本"""
    global _ACCURACY_CONSTRAINTS
    if _ACCURACY_CONSTRAINTS is None:
        prompt_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
        filepath = os.path.join(prompt_dir, "accuracy_constraints.txt")
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                _ACCURACY_CONSTRAINTS = f.read()
        else:
            _ACCURACY_CONSTRAINTS = ""
    return _ACCURACY_CONSTRAINTS


def append_constraints(prompt: str) -> str:
    """在 prompt 尾部追加精准性约束（不修改原有 prompt 内容）"""
    constraints = get_accuracy_constraints()
    if constraints:
        return prompt + "\n\n" + constraints
    return prompt