"""Supervisor + worker 多智能体 harness。"""

from .config import HarnessConfig
from .runner import Harness, RunOutcome

__all__ = ["Harness", "HarnessConfig", "RunOutcome", "__version__"]

__version__ = "0.1.0"
