"""Multi-method convergence engine (see docs/INTENT_CONVERGENCE_SPEC.md and _PLAN.md).

Importing this package is cheap; heavy modules (dedup/natal/promise import the
engine stack) are imported explicitly by callers.
"""
from .types import (Evidence, IntentConfig, IntentConfigError, PillarResult, PromiseFactor,  # noqa: F401
                    PromiseResult, WindowResult)
