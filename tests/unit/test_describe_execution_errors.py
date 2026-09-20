"""T68 — describe_execution names IAM denials instead of 500ing.

N2 finding: on the live stack, GET /executions/{arn} returned a bare
`{"error": "internal error"}` (500) for every ARN — including ARNs that never
existed — because the Lambda's AccessDeniedException escaped `call()`'s
mapping. The execution-status channel is exactly what an operator needs when a
compile dies, so a permissions problem must be named, not masked.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from services.api import actions  # noqa: E402


class _Denied:
    """Fake stepfunctions client whose describe is denied by IAM."""

    class exceptions:  # noqa: N801 - boto3 client exception namespace
        ExecutionDoesNotExist = type("ExecutionDoesNotExist", (Exception,), {})

    def describe_execution(self, executionArn):  # noqa: N803
        raise self.exceptions.AccessDeniedException(
            "User ... is not authorized to perform: states:DescribeExecution")


def test_describe_execution_maps_access_denied_to_permission_error(monkeypatch):
    import sys as _sys
    fake = _Denied()
    fake_mod = type(sys)("boto3")
    fake_mod.client = lambda name: fake
    monkeypatch.setitem(_sys.modules, "boto3", fake_mod)

    with pytest.raises(PermissionError) as ei:
        actions.describe_execution(
            "arn:aws:states:ap-south-1:054728709828:execution:machine:nope")
    assert "states:DescribeExecution" in str(ei.value)


def test_describe_execution_still_404s_for_missing_executions(monkeypatch):
    import sys as _sys
    fake = _Denied()

    class _Missing(_Denied):
        def describe_execution(self, executionArn):  # noqa: N803
            raise fake.exceptions.ExecutionDoesNotExist(executionArn)

    fake_mod = type(sys)("boto3")
    fake_mod.client = lambda name: _Missing()
    monkeypatch.setitem(_sys.modules, "boto3", fake_mod)

    with pytest.raises(KeyError):
        actions.describe_execution(
            "arn:aws:states:ap-south-1:054728709828:execution:machine:gone")
