"""Enumerations for job and work-item lifecycle states."""
from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    PENDING = "PENDING"
    INGESTING = "INGESTING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ItemStatus(str, Enum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
