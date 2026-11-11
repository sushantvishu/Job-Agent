"""
app/fsm.py — Finite State Machine for Job Application Lifecycle.

Provides typed job states and validates allowed transitions to prevent
corrupted pipeline state jumps (e.g. from rejected straight to applied).
"""
from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    DISCOVERED = "scouted"
    SHORTLISTED = "shortlisted"
    STAGED = "filled_pending_submit"
    NEEDS_MANUAL_INPUT = "needs_manual_input"
    APPLIED = "applied"
    SKIPPED = "skipped"
    ERROR = "error"
    INTERVIEWING = "interviewing"
    REJECTED = "rejected"


class InvalidStateTransitionError(ValueError):
    """Raised when an application attempts an illegal state transition."""


class ApplicationFSM:
    """Finite State Machine enforcing valid lifecycle transitions for job applications."""

    ALLOWED_TRANSITIONS: dict[JobState, set[JobState]] = {
        JobState.DISCOVERED: {
            JobState.SHORTLISTED,
            JobState.SKIPPED,
            JobState.ERROR,
            JobState.APPLIED,
            JobState.STAGED,
        },
        JobState.SHORTLISTED: {
            JobState.STAGED,
            JobState.NEEDS_MANUAL_INPUT,
            JobState.APPLIED,
            JobState.SKIPPED,
            JobState.ERROR,
        },
        JobState.STAGED: {
            JobState.APPLIED,
            JobState.NEEDS_MANUAL_INPUT,
            JobState.SKIPPED,
            JobState.ERROR,
            JobState.SHORTLISTED,
        },
        JobState.NEEDS_MANUAL_INPUT: {
            JobState.APPLIED,
            JobState.STAGED,
            JobState.SKIPPED,
            JobState.ERROR,
        },
        JobState.APPLIED: {
            JobState.INTERVIEWING,
            JobState.REJECTED,
        },
        JobState.SKIPPED: {
            JobState.SHORTLISTED,  # Recovered during recheck-skipped
            JobState.APPLIED,      # Detected already applied on site
        },
        JobState.ERROR: {
            JobState.SHORTLISTED,
            JobState.NEEDS_MANUAL_INPUT,
            JobState.SKIPPED,
        },
        JobState.INTERVIEWING: {
            JobState.REJECTED,
        },
        JobState.REJECTED: set(),
    }

    @classmethod
    def can_transition(cls, from_state: str | JobState, to_state: str | JobState) -> bool:
        """Return True if transitioning from from_state to to_state is valid."""
        try:
            curr = from_state if isinstance(from_state, JobState) else JobState(str(from_state))
            target = to_state if isinstance(to_state, JobState) else JobState(str(to_state))
        except ValueError:
            # Tolerant of unmapped legacy states
            return True
        if curr == target:
            return True
        allowed = cls.ALLOWED_TRANSITIONS.get(curr, set())
        return target in allowed

    @classmethod
    def validate_transition(cls, from_state: str | JobState, to_state: str | JobState) -> None:
        """Validate state transition; raises InvalidStateTransitionError if illegal."""
        if not cls.can_transition(from_state, to_state):
            raise InvalidStateTransitionError(
                f"Illegal job application state transition from '{from_state}' to '{to_state}'."
            )
