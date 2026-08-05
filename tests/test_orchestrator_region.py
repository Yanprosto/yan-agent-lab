import math

import pytest

from mcbuild.orchestrator.region import ModelValidationError, RegionExpr


def shape(kind, **values):
    return RegionExpr.from_dict({"op": "shape", "shape": {"kind": kind, **values}})


def test_axis_aligned_rectangle_contains_inclusive_boundary_and_negative_coordinates():
    region = shape("axis_aligned_rectangle", min_x=-3, max_x=2, min_z=-4, max_z=1)
    assert region.contains(-3, -4)
    assert region.contains(2, 1)
    assert region.contains(0, 0)
    assert not region.contains(-3.01, 0)
    assert region.bounds() == (-3, 2, -4, 1)


def test_rotated_rectangle_uses_inverse_rotation_and_conservative_bounds():
    region = shape("rotated_rectangle", center=[0, 0], width=4, depth=2, rotation=90)
    assert region.contains(0, 2)  # inclusive end of the rotated width axis
    assert region.contains(1, 0)  # inclusive end of the rotated depth axis
    assert not region.contains(1.1, 0)
    assert region.bounds() == (-1, 1, -2, 2)

    diagonal = shape("rotated_rectangle", center=[0, 0], width=4, depth=2, rotation=45)
    assert diagonal.bounds() == (-3, 3, -3, 3)


def test_circle_and_ellipse_include_boundaries():
    circle = shape("circle", center=[-2, 3], radius=2)
    ellipse = shape("ellipse", center=[1, -1], radius_x=4, radius_z=2)
    assert circle.contains(-4, 3)
    assert not circle.contains(-4.01, 3)
    assert circle.bounds() == (-4, 0, 1, 5)
    assert ellipse.contains(5, -1)
    assert ellipse.contains(1, 1)
    assert not ellipse.contains(5.01, -1)


def test_polygon_contains_edges_and_vertices_deterministically():
    polygon = shape("polygon", points=[[-2, -1], [4, -1], [1, 3]])
    assert polygon.contains(-2, -1)
    assert polygon.contains(1, -1)  # horizontal edge
    assert polygon.contains(1, 3)
    assert polygon.contains(1, 0)
    assert not polygon.contains(4, 3)
    assert polygon.bounds() == (-2, 4, -1, 3)


def test_union_intersection_and_difference_have_inclusive_boolean_semantics():
    left = shape("axis_aligned_rectangle", min_x=-2, max_x=1, min_z=-1, max_z=1)
    right = shape("axis_aligned_rectangle", min_x=0, max_x=3, min_z=-1, max_z=1)
    union = RegionExpr.from_dict({"op": "union", "children": [left.to_dict(), right.to_dict()]})
    intersection = RegionExpr.from_dict({"op": "intersection", "children": [left.to_dict(), right.to_dict()]})
    difference = RegionExpr.from_dict({"op": "difference", "base": left.to_dict(), "subtract": [right.to_dict()]})
    assert union.contains(-2, 0) and union.contains(3, 0)
    assert intersection.rasterize() == {(0, -1), (0, 0), (0, 1), (1, -1), (1, 0), (1, 1)}
    assert not difference.contains(0, 0)  # subtract boundaries are removed
    assert difference.contains(-1, 0)


def test_disjoint_intersection_has_no_bounds_or_cells():
    first = shape("circle", center=[-10, 0], radius=1)
    second = shape("circle", center=[10, 0], radius=1)
    region = RegionExpr.intersection(first, second)
    assert region.bounds() is None
    assert list(region.iter_cells()) == []
    assert region.rasterize() == set()


def test_iter_cells_can_be_clipped_to_explicit_bounds():
    region = shape("axis_aligned_rectangle", min_x=-2, max_x=2, min_z=-2, max_z=2)
    assert list(region.iter_cells((0, 1, 0, 1))) == [(0, 0), (0, 1), (1, 0), (1, 1)]


def test_region_round_trip_preserves_nested_expression():
    data = {
        "op": "difference",
        "base": {
            "op": "union",
            "children": [
                {"op": "shape", "shape": {"kind": "circle", "center": [-4, 2], "radius": 3}},
                {
                    "op": "shape",
                    "shape": {
                        "kind": "rotated_rectangle",
                        "center": [2, -1],
                        "width": 5,
                        "depth": 2,
                        "rotation": 30,
                    },
                },
            ],
        },
        "subtract": [
            {
                "op": "shape",
                "shape": {"kind": "polygon", "points": [[-1, -1], [1, -1], [0, 2]]},
            }
        ],
    }
    decoded = RegionExpr.from_dict(data)
    assert RegionExpr.from_dict(decoded.to_dict()) == decoded


@pytest.mark.parametrize(
    ("data", "path_fragment"),
    [
        ({"op": "shape", "shape": {"kind": "circle", "center": [0, 0], "radius": math.inf}}, "radius"),
        ({"op": "union", "children": []}, "children"),
        ({"op": "shape", "shape": {"kind": "circle", "center": [0, 0], "radius": 2, "extra": 1}}, "unknown"),
        ({"op": "shape", "shape": {"kind": "polygon", "points": [[0, 0], [1, 1], [2, 2]]}}, "points"),
    ],
)
def test_region_rejects_invalid_external_data_with_path(data, path_fragment):
    with pytest.raises(ModelValidationError) as exc_info:
        RegionExpr.from_dict(data, path="$.responsibility.core")
    assert "$.responsibility.core" in str(exc_info.value)
    assert path_fragment in str(exc_info.value)
