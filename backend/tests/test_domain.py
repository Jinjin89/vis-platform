import pytest

from vis_platform_backend.contracts.plot_runs import RunStatus
from vis_platform_backend.domain.plot_runs import can_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.QUEUED, RunStatus.RUNNING),
        (RunStatus.RUNNING, RunStatus.COMPLETED),
        (RunStatus.AWAITING_INPUT, RunStatus.RUNNING),
    ],
)
def test_allowed_transitions(current: RunStatus, target: RunStatus) -> None:
    assert can_transition(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (RunStatus.COMPLETED, RunStatus.RUNNING),
        (RunStatus.FAILED, RunStatus.QUEUED),
        (RunStatus.CANCELLED, RunStatus.RUNNING),
    ],
)
def test_terminal_states_cannot_transition(current: RunStatus, target: RunStatus) -> None:
    assert not can_transition(current, target)
