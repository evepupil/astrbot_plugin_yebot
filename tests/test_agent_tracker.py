from yebot.runtime.agents import AgentBudget, AgentRequestTracker, RunStatus


def test_tracker_shares_step_limit_across_repeated_tool_calls() -> None:
    now = [10.0]
    tracker = AgentRequestTracker(
        AgentBudget(max_steps=2, timeout_seconds=30), clock=lambda: now[0]
    )

    first = tracker.reserve("request-1")
    second = tracker.reserve("request-1")
    third = tracker.reserve("request-1")

    assert (first.allowed, first.steps_used) == (True, 1)
    assert (second.allowed, second.steps_used) == (True, 2)
    assert (third.allowed, third.status) == (False, RunStatus.STEP_LIMIT)


def test_tracker_returns_timeout_without_retaining_content() -> None:
    now = [10.0]
    tracker = AgentRequestTracker(
        AgentBudget(max_steps=3, timeout_seconds=5), clock=lambda: now[0]
    )

    assert tracker.reserve("request-2").allowed
    now[0] = 15.0
    expired = tracker.reserve("request-2")

    assert not expired.allowed
    assert expired.status is RunStatus.TIMEOUT
    assert expired.steps_used == 1


def test_tracker_does_not_share_empty_request_ids() -> None:
    tracker = AgentRequestTracker(AgentBudget(max_steps=1))

    assert tracker.reserve("").allowed
    assert tracker.reserve("").allowed
