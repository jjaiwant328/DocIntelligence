"""Adapters resolve a skill's implementation reference to a concrete call.
Exactly three kinds; never dynamic code-exec from YAML (ADR-005)."""
from .uc_function import UCFunctionAdapter
from .internal_call import InternalCallAdapter
from .llm_schema import LLMSchemaAdapter

DEFAULT_ADAPTERS = {
    "uc_function": UCFunctionAdapter(),
    "internal_call": InternalCallAdapter(),
    "llm_schema": LLMSchemaAdapter(),
}

__all__ = ["UCFunctionAdapter", "InternalCallAdapter", "LLMSchemaAdapter",
           "DEFAULT_ADAPTERS"]
