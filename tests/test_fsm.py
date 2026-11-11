import pytest
from app.fsm import ApplicationFSM, InvalidStateTransitionError, JobState


def test_fsm_valid_transitions():
    # Valid forward flow
    assert ApplicationFSM.can_transition(JobState.DISCOVERED, JobState.SHORTLISTED)
    assert ApplicationFSM.can_transition(JobState.SHORTLISTED, JobState.STAGED)
    assert ApplicationFSM.can_transition(JobState.STAGED, JobState.APPLIED)
    assert ApplicationFSM.can_transition(JobState.APPLIED, JobState.INTERVIEWING)
    assert ApplicationFSM.can_transition(JobState.INTERVIEWING, JobState.REJECTED)

    # Manual input checkpoint flow
    assert ApplicationFSM.can_transition(JobState.SHORTLISTED, JobState.NEEDS_MANUAL_INPUT)
    assert ApplicationFSM.can_transition(JobState.NEEDS_MANUAL_INPUT, JobState.APPLIED)


def test_fsm_invalid_transitions():
    # Cannot jump from REJECTED straight to APPLIED
    assert not ApplicationFSM.can_transition(JobState.REJECTED, JobState.APPLIED)

    # Validate transition raises error on illegal jump
    with pytest.raises(InvalidStateTransitionError):
        ApplicationFSM.validate_transition(JobState.REJECTED, JobState.APPLIED)


def test_fsm_self_transition():
    # Remaining in same state is always permissible (e.g. updating notes)
    assert ApplicationFSM.can_transition(JobState.SHORTLISTED, JobState.SHORTLISTED)
    assert ApplicationFSM.can_transition(JobState.APPLIED, JobState.APPLIED)
