"""Tests for spatial relation computation in OmniParser client."""

from server.services.omniparser_client import _compute_spatial_relations
from server.models.schemas import UIElement


def make_el(eid, x1, y1, x2, y2):
    return UIElement(
        element_id=str(eid),
        bbox=[x1, y1, x2, y2],
        element_type="text",
        text=f"el{eid}",
        confidence=0.9,
        center=[(x1 + x2) // 2, (y1 + y2) // 2],
    )


def test_same_row_detection():
    """Two elements on the same y-band should be mutual left/right neighbors."""
    e1 = make_el(1, 100, 100, 200, 150)  # y: 100-150
    e2 = make_el(2, 250, 105, 350, 155)  # y: 105-155, high y-overlap = same row
    _compute_spatial_relations([e1, e2])
    assert e1.right_elem_ids == ["2"]
    assert e2.left_elem_ids == ["1"]


def test_different_rows_no_horizontal_rel():
    """Elements far apart vertically should NOT be left/right neighbors."""
    e1 = make_el(1, 100, 100, 200, 150)
    e2 = make_el(2, 250, 500, 350, 550)  # completely different row
    _compute_spatial_relations([e1, e2])
    assert e1.right_elem_ids == []
    assert e2.left_elem_ids == []


def test_top_bottom_relations():
    """Elements with y-overlap should get top/bottom relations."""
    e1 = make_el(1, 100, 50, 300, 120)
    e2 = make_el(2, 150, 150, 250, 250)
    _compute_spatial_relations([e1, e2])
    assert "2" in e1.bottom_elem_ids
    assert "1" in e2.top_elem_ids


def test_capped_neighbors():
    """Neighbor lists should be capped at specified limits."""
    elements = []
    for i in range(10):
        elements.append(make_el(i, i * 80, 100, i * 80 + 60, 150))
    _compute_spatial_relations(elements)
    for el in elements:
        assert len(el.left_elem_ids) <= 5
        assert len(el.right_elem_ids) <= 5


def test_empty_elements():
    """Empty element list should not crash."""
    _compute_spatial_relations([])


def test_single_element():
    """Single element should have no neighbors."""
    e1 = make_el(1, 100, 100, 200, 150)
    _compute_spatial_relations([e1])
    assert e1.left_elem_ids == []
    assert e1.right_elem_ids == []
    assert e1.top_elem_ids == []
    assert e1.bottom_elem_ids == []


def test_degenerate_bbox_no_crash():
    """Element with zero-height bbox should not crash."""
    e1 = make_el(1, 100, 100, 200, 100)  # zero height
    e2 = make_el(2, 250, 105, 350, 155)
    _compute_spatial_relations([e1, e2])  # should not raise


def test_element_id_strips_tilde():
    """parse_screenshot_full should strip ~ prefix from element IDs."""
    # This test requires mocking the HTTP call — see integration tests.
    pass  # placeholder for Task 9 integration test
