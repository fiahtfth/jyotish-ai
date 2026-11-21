"""JSON-safe conversion for convergence results (dataclasses, frozensets, dates)."""
from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Any


def jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        label = getattr(type(obj), "label", None)
        if isinstance(label, property):
            out["label"] = obj.label
        return out
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()[:10] if not isinstance(obj, datetime) else obj.isoformat()
    if isinstance(obj, (frozenset, set)):
        return sorted(jsonable(x) for x in obj)
    if isinstance(obj, (list, tuple)):
        return [jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if hasattr(obj, "items") and callable(obj.items):          # MappingProxyType
        return {str(k): jsonable(v) for k, v in obj.items()}
    return obj
