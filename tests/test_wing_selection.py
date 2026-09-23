"""selidx: the console's strip selection, 0-based and contiguous."""

import pytest

from kite.wing_link import selidx_to_strip


@pytest.mark.parametrize("idx,strip", [
    (0, ("ch", 1)), (39, ("ch", 40)),
    (40, ("aux", 1)), (47, ("aux", 8)),
    (48, ("bus", 1)), (63, ("bus", 16)),
    (64, ("main", 1)), (67, ("main", 4)),
    (68, ("mtx", 1)), (75, ("mtx", 8)),
])
def test_every_family_boundary(idx, strip):
    assert selidx_to_strip(idx) == strip


def test_outside_the_range_is_nothing():
    # 76 and up do not exist, and DCAs never appear here at all: they carry no
    # audio, so they have no insert and no rack to open.
    assert selidx_to_strip(76) is None
    assert selidx_to_strip(-1) is None
    assert selidx_to_strip(None) is None
