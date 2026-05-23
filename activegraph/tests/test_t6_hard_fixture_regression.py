"""Regression fixture for T6 hard verifier.

Bug source: comment:activegraph/t6_hard_fixture_module.py:1.
Correct behavior: fixture_helper doubles the integer input.
Current behavior at commit A: the module does not exist, so importing it fails.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from activegraph.t6_hard_fixture_module import fixture_helper


def test_fixture_helper_doubles_input() -> None:
    assert fixture_helper(4) == 8
