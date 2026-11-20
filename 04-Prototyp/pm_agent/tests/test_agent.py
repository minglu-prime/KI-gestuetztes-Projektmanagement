import pytest

from pm_agent.agent import PlanningError, raise_for_stop_reason


@pytest.mark.parametrize(
    "stop_reason, category, message",
    [
        ("length", None, "Die Antwort vom Agenten wurde abgeschnitten"),
        ("content_filter", None, r"Der Agent hat die Anfrage abgelehnt\."),
        (
            "stop",
            "Das kann ich nicht.",
            r"Der Agent hat die Anfrage abgelehnt: Das kann ich nicht\.",
        ),
    ],
)
def test_a_reply_that_cannot_lead_to_a_plan_is_an_error(stop_reason, category, message):
    # Without the check such a reply would end the run with "no result" and no reason.
    with pytest.raises(PlanningError, match=message):
        raise_for_stop_reason(stop_reason, category)


@pytest.mark.parametrize("stop_reason", ["tool_calls", "stop"])
def test_regular_replies_pass(stop_reason):
    raise_for_stop_reason(stop_reason, None)
