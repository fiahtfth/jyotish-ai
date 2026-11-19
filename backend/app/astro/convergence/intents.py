"""Loader/validator over backend/data/intents/<NN>_<ID>.json (61 intent configs)."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .types import IntentConfig, IntentConfigError

DIR = Path(__file__).resolve().parents[3] / "data" / "intents"
_NAME = re.compile(r"^(\d{2})_([A-Z][A-Z0-9_]+)\.json$")


@lru_cache(maxsize=1)
def load_all() -> dict:
    """{number: IntentConfig}; raises IntentConfigError on any invalid/duplicate/misnamed file."""
    out: dict = {}
    ids: set = set()
    for path in sorted(DIR.glob("*.json")):
        m = _NAME.match(path.name)
        if not m:
            raise IntentConfigError(f"{path.name}: file must be named <NN>_<INTENT_ID>.json")
        try:
            cfg = IntentConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except IntentConfigError as exc:
            raise IntentConfigError(f"{path.name}: {exc}") from None
        if cfg.number != int(m.group(1)) or cfg.intent_id != m.group(2):
            raise IntentConfigError(f"{path.name}: filename does not match number/intent_id")
        if cfg.number in out or cfg.intent_id in ids:
            raise IntentConfigError(f"{path.name}: duplicate number or intent_id")
        out[cfg.number] = cfg
        ids.add(cfg.intent_id)
    return out


def get(key) -> Optional[IntentConfig]:
    """Resolve by number, spec intent_id, or legacy registry id (via legacy_ids)."""
    cfgs = load_all()
    if isinstance(key, int):
        return cfgs.get(key)
    for c in cfgs.values():
        if c.intent_id == key or key in c.legacy_ids:
            return c
    return None


def by_phase(phase: int) -> list:
    return [c for _, c in sorted(load_all().items()) if c.phase == phase]
