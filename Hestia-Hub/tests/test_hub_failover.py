"""Failover only when a write never reached the instance (core review 2026-11-27 §4.6)."""
from __future__ import annotations

import pytest
import requests
from urllib3.exceptions import MaxRetryError, NewConnectionError, ProtocolError

from modules.router import may_fail_over


def _refused() -> requests.ConnectionError:
    return requests.ConnectionError(MaxRetryError(None, "http://a/x", reason=NewConnectionError(None, "refused")))


@pytest.mark.unit
class TestMayFailOver:
    def test_reads_always_fail_over(self):
        assert may_fail_over("GET", requests.ReadTimeout("slow"))
        assert may_fail_over("get", _refused())

    def test_write_fails_over_when_never_reached(self):
        assert may_fail_over("POST", _refused())
        assert may_fail_over("POST", requests.ConnectTimeout("connect timed out"))

    def test_write_is_not_repeated_after_a_read_timeout(self):
        assert not may_fail_over("POST", requests.ReadTimeout("read timed out"))
        assert not may_fail_over("DELETE", requests.ReadTimeout("read timed out"))

    def test_write_is_not_repeated_after_a_cut_mid_answer(self):
        cut = requests.ConnectionError(ProtocolError("Connection aborted.", ConnectionResetError()))
        assert not may_fail_over("POST", cut)
