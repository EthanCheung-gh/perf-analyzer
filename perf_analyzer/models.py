from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    threshold_label: str
    default_threshold: float
    higher_is_worse: bool = True
