import pytest

from activegraph.policy import Policy


pytestmark = getattr(pytest.mark, "activegraph.policy.Policy")


def test_activegraph_policy_policy_defaults_are_isolated() -> None:
    first = Policy()
    second = Policy()

    first.can_create.append("claim")

    assert first.behavior is None
    assert first.can_create == ["claim"]
    assert second.can_create == []
    assert second.can_call_tool == []


def test_activegraph_policy_policy_accepts_explicit_capabilities() -> None:
    policy = Policy(
        behavior="reviewer",
        can_create=["claim"],
        can_create_relation=["supports"],
        can_propose=["memo"],
        can_apply=["patch"],
        can_call_tool=["search"],
        requires_approval=["delete"],
    )

    assert policy.behavior == "reviewer"
    assert policy.can_create == ["claim"]
    assert policy.can_create_relation == ["supports"]
    assert policy.can_propose == ["memo"]
    assert policy.can_apply == ["patch"]
    assert policy.can_call_tool == ["search"]
    assert policy.requires_approval == ["delete"]
