"""Deterministic two-dimensional region expressions for project responsibilities.

Regions are sampled at integer Minecraft ``(x, z)`` coordinates.  Every primitive
includes its mathematical boundary; boolean operations preserve that convention.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, TypeAlias

Bounds2D: TypeAlias = tuple[int, int, int, int]
Cell2D: TypeAlias = tuple[int, int]

_EPSILON = 1e-9


class ModelValidationError(ValueError):
    """A strict model/region decoding error with a JSON-style field path."""

    def __init__(self, path: str, message: str) -> None:
        self.path = path
        self.message = message
        super().__init__(f"{path}: {message}")


class ShapeKind(StrEnum):
    AXIS_ALIGNED_RECTANGLE = "axis_aligned_rectangle"
    ROTATED_RECTANGLE = "rotated_rectangle"
    CIRCLE = "circle"
    ELLIPSE = "ellipse"
    POLYGON = "polygon"


class RegionOp(StrEnum):
    SHAPE = "shape"
    UNION = "union"
    INTERSECTION = "intersection"
    DIFFERENCE = "difference"


def _expect_mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelValidationError(path, "must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ModelValidationError(path, "object keys must be strings")
    return value


def _check_fields(
    data: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | frozenset[str] = frozenset(),
    path: str,
) -> None:
    missing = sorted(required - set(data))
    if missing:
        raise ModelValidationError(path, f"missing required field(s): {', '.join(missing)}")
    unknown = sorted(set(data) - required - optional)
    if unknown:
        raise ModelValidationError(path, f"unknown field(s): {', '.join(unknown)}")


def _expect_number(value: Any, path: str) -> float:
    if type(value) not in (int, float):
        raise ModelValidationError(path, "must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ModelValidationError(path, "must be a finite number")
    return result


def _expect_sequence(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise ModelValidationError(path, "must be an array")
    return value


def _expect_point(value: Any, path: str) -> tuple[float, float]:
    sequence = _expect_sequence(value, path)
    if len(sequence) != 2:
        raise ModelValidationError(path, "must contain exactly two coordinates")
    return _expect_number(sequence[0], f"{path}[0]"), _expect_number(sequence[1], f"{path}[1]")


def _floor(value: float) -> int:
    return math.floor(value + _EPSILON)


def _ceil(value: float) -> int:
    return math.ceil(value - _EPSILON)


@dataclass(frozen=True)
class AxisAlignedRectangle:
    min_x: float
    max_x: float
    min_z: float
    max_z: float
    kind: ShapeKind = ShapeKind.AXIS_ALIGNED_RECTANGLE

    def __post_init__(self) -> None:
        _validate_finite_fields(self, "min_x", "max_x", "min_z", "max_z")
        if self.min_x > self.max_x:
            raise ModelValidationError("$.min_x", "must be less than or equal to max_x")
        if self.min_z > self.max_z:
            raise ModelValidationError("$.min_z", "must be less than or equal to max_z")

    def contains(self, x: float, z: float) -> bool:
        return (
            self.min_x - _EPSILON <= x <= self.max_x + _EPSILON and self.min_z - _EPSILON <= z <= self.max_z + _EPSILON
        )

    def bounds(self) -> Bounds2D:
        return _floor(self.min_x), _ceil(self.max_x), _floor(self.min_z), _ceil(self.max_z)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "min_x": self.min_x,
            "max_x": self.max_x,
            "min_z": self.min_z,
            "max_z": self.max_z,
        }


@dataclass(frozen=True)
class RotatedRectangle:
    center: tuple[float, float]
    width: float
    depth: float
    rotation: float
    kind: ShapeKind = ShapeKind.ROTATED_RECTANGLE

    def __post_init__(self) -> None:
        if len(self.center) != 2:
            raise ModelValidationError("$.center", "must contain exactly two coordinates")
        _validate_finite_values(self.center, "$.center")
        _validate_finite_fields(self, "width", "depth", "rotation")
        if self.width <= 0:
            raise ModelValidationError("$.width", "must be greater than zero")
        if self.depth <= 0:
            raise ModelValidationError("$.depth", "must be greater than zero")

    def contains(self, x: float, z: float) -> bool:
        angle = math.radians(self.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        dx = x - self.center[0]
        dz = z - self.center[1]
        local_x = dx * cos_a + dz * sin_a
        local_z = -dx * sin_a + dz * cos_a
        return abs(local_x) <= self.width / 2 + _EPSILON and abs(local_z) <= self.depth / 2 + _EPSILON

    def bounds(self) -> Bounds2D:
        angle = math.radians(self.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        half_width = self.width / 2
        half_depth = self.depth / 2
        corners = []
        for local_x, local_z in (
            (-half_width, -half_depth),
            (-half_width, half_depth),
            (half_width, -half_depth),
            (half_width, half_depth),
        ):
            x = self.center[0] + local_x * cos_a - local_z * sin_a
            z = self.center[1] + local_x * sin_a + local_z * cos_a
            corners.append((x, z))
        xs = [point[0] for point in corners]
        zs = [point[1] for point in corners]
        return _floor(min(xs)), _ceil(max(xs)), _floor(min(zs)), _ceil(max(zs))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "center": list(self.center),
            "width": self.width,
            "depth": self.depth,
            "rotation": self.rotation,
        }


@dataclass(frozen=True)
class Circle:
    center: tuple[float, float]
    radius: float
    kind: ShapeKind = ShapeKind.CIRCLE

    def __post_init__(self) -> None:
        if len(self.center) != 2:
            raise ModelValidationError("$.center", "must contain exactly two coordinates")
        _validate_finite_values(self.center, "$.center")
        _validate_finite_fields(self, "radius")
        if self.radius <= 0:
            raise ModelValidationError("$.radius", "must be greater than zero")

    def contains(self, x: float, z: float) -> bool:
        dx = x - self.center[0]
        dz = z - self.center[1]
        return dx * dx + dz * dz <= self.radius * self.radius + _EPSILON

    def bounds(self) -> Bounds2D:
        return (
            _floor(self.center[0] - self.radius),
            _ceil(self.center[0] + self.radius),
            _floor(self.center[1] - self.radius),
            _ceil(self.center[1] + self.radius),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "center": list(self.center), "radius": self.radius}


@dataclass(frozen=True)
class Ellipse:
    center: tuple[float, float]
    radius_x: float
    radius_z: float
    kind: ShapeKind = ShapeKind.ELLIPSE

    def __post_init__(self) -> None:
        if len(self.center) != 2:
            raise ModelValidationError("$.center", "must contain exactly two coordinates")
        _validate_finite_values(self.center, "$.center")
        _validate_finite_fields(self, "radius_x", "radius_z")
        if self.radius_x <= 0:
            raise ModelValidationError("$.radius_x", "must be greater than zero")
        if self.radius_z <= 0:
            raise ModelValidationError("$.radius_z", "must be greater than zero")

    def contains(self, x: float, z: float) -> bool:
        dx = (x - self.center[0]) / self.radius_x
        dz = (z - self.center[1]) / self.radius_z
        return dx * dx + dz * dz <= 1 + _EPSILON

    def bounds(self) -> Bounds2D:
        return (
            _floor(self.center[0] - self.radius_x),
            _ceil(self.center[0] + self.radius_x),
            _floor(self.center[1] - self.radius_z),
            _ceil(self.center[1] + self.radius_z),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "center": list(self.center),
            "radius_x": self.radius_x,
            "radius_z": self.radius_z,
        }


@dataclass(frozen=True)
class Polygon:
    points: tuple[tuple[float, float], ...]
    kind: ShapeKind = ShapeKind.POLYGON

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ModelValidationError("$.points", "must contain at least three points")
        for index, point in enumerate(self.points):
            if len(point) != 2:
                raise ModelValidationError(f"$.points[{index}]", "must contain exactly two coordinates")
            _validate_finite_values(point, f"$.points[{index}]")
        twice_area = sum(
            x1 * z2 - x2 * z1 for (x1, z1), (x2, z2) in zip(self.points, self.points[1:] + self.points[:1], strict=True)
        )
        if abs(twice_area) <= _EPSILON:
            raise ModelValidationError("$.points", "must describe a polygon with non-zero area")

    def contains(self, x: float, z: float) -> bool:
        inside = False
        previous = self.points[-1]
        for current in self.points:
            if _point_on_segment(x, z, previous[0], previous[1], current[0], current[1]):
                return True
            x1, z1 = previous
            x2, z2 = current
            if (z1 > z) != (z2 > z):
                crossing_x = (x2 - x1) * (z - z1) / (z2 - z1) + x1
                if x < crossing_x:
                    inside = not inside
            previous = current
        return inside

    def bounds(self) -> Bounds2D:
        xs = [point[0] for point in self.points]
        zs = [point[1] for point in self.points]
        return _floor(min(xs)), _ceil(max(xs)), _floor(min(zs)), _ceil(max(zs))

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "points": [list(point) for point in self.points]}


RegionShape: TypeAlias = AxisAlignedRectangle | RotatedRectangle | Circle | Ellipse | Polygon


def _validate_finite_fields(instance: object, *names: str) -> None:
    for name in names:
        value = getattr(instance, name)
        if type(value) not in (int, float) or not math.isfinite(float(value)):
            raise ModelValidationError(f"$.{name}", "must be a finite number")


def _validate_finite_values(values: Sequence[float], path: str) -> None:
    for index, value in enumerate(values):
        if type(value) not in (int, float) or not math.isfinite(float(value)):
            raise ModelValidationError(f"{path}[{index}]", "must be a finite number")


def _point_on_segment(
    x: float,
    z: float,
    x1: float,
    z1: float,
    x2: float,
    z2: float,
) -> bool:
    cross = (x - x1) * (z2 - z1) - (z - z1) * (x2 - x1)
    scale = max(1.0, abs(x2 - x1), abs(z2 - z1))
    if abs(cross) > _EPSILON * scale:
        return False
    return (
        min(x1, x2) - _EPSILON <= x <= max(x1, x2) + _EPSILON and min(z1, z2) - _EPSILON <= z <= max(z1, z2) + _EPSILON
    )


def _shape_from_dict(value: Any, path: str) -> RegionShape:
    data = _expect_mapping(value, path)
    kind_value = data.get("kind")
    if not isinstance(kind_value, str):
        raise ModelValidationError(f"{path}.kind", "must be a string")
    try:
        kind = ShapeKind(kind_value)
    except ValueError as exc:
        choices = ", ".join(item.value for item in ShapeKind)
        raise ModelValidationError(f"{path}.kind", f"must be one of: {choices}") from exc

    if kind is ShapeKind.AXIS_ALIGNED_RECTANGLE:
        fields = {"kind", "min_x", "max_x", "min_z", "max_z"}
        _check_fields(data, required=fields, path=path)
        min_x = _expect_number(data["min_x"], f"{path}.min_x")
        max_x = _expect_number(data["max_x"], f"{path}.max_x")
        min_z = _expect_number(data["min_z"], f"{path}.min_z")
        max_z = _expect_number(data["max_z"], f"{path}.max_z")
        if min_x > max_x:
            raise ModelValidationError(f"{path}.min_x", "must be less than or equal to max_x")
        if min_z > max_z:
            raise ModelValidationError(f"{path}.min_z", "must be less than or equal to max_z")
        return AxisAlignedRectangle(min_x, max_x, min_z, max_z)

    if kind is ShapeKind.ROTATED_RECTANGLE:
        fields = {"kind", "center", "width", "depth", "rotation"}
        _check_fields(data, required=fields, path=path)
        center = _expect_point(data["center"], f"{path}.center")
        width = _expect_number(data["width"], f"{path}.width")
        depth = _expect_number(data["depth"], f"{path}.depth")
        rotation = _expect_number(data["rotation"], f"{path}.rotation")
        if width <= 0:
            raise ModelValidationError(f"{path}.width", "must be greater than zero")
        if depth <= 0:
            raise ModelValidationError(f"{path}.depth", "must be greater than zero")
        return RotatedRectangle(center, width, depth, rotation)

    if kind is ShapeKind.CIRCLE:
        fields = {"kind", "center", "radius"}
        _check_fields(data, required=fields, path=path)
        center = _expect_point(data["center"], f"{path}.center")
        radius = _expect_number(data["radius"], f"{path}.radius")
        if radius <= 0:
            raise ModelValidationError(f"{path}.radius", "must be greater than zero")
        return Circle(center, radius)

    if kind is ShapeKind.ELLIPSE:
        fields = {"kind", "center", "radius_x", "radius_z"}
        _check_fields(data, required=fields, path=path)
        center = _expect_point(data["center"], f"{path}.center")
        radius_x = _expect_number(data["radius_x"], f"{path}.radius_x")
        radius_z = _expect_number(data["radius_z"], f"{path}.radius_z")
        if radius_x <= 0:
            raise ModelValidationError(f"{path}.radius_x", "must be greater than zero")
        if radius_z <= 0:
            raise ModelValidationError(f"{path}.radius_z", "must be greater than zero")
        return Ellipse(center, radius_x, radius_z)

    fields = {"kind", "points"}
    _check_fields(data, required=fields, path=path)
    raw_points = _expect_sequence(data["points"], f"{path}.points")
    if len(raw_points) < 3:
        raise ModelValidationError(f"{path}.points", "must contain at least three points")
    points = tuple(_expect_point(point, f"{path}.points[{index}]") for index, point in enumerate(raw_points))
    try:
        return Polygon(points)
    except ModelValidationError as exc:
        suffix = exc.path.removeprefix("$")
        raise ModelValidationError(f"{path}{suffix}", exc.message) from exc


def _intersect_bounds(left: Bounds2D, right: Bounds2D) -> Bounds2D | None:
    min_x = max(left[0], right[0])
    max_x = min(left[1], right[1])
    min_z = max(left[2], right[2])
    max_z = min(left[3], right[3])
    if min_x > max_x or min_z > max_z:
        return None
    return min_x, max_x, min_z, max_z


@dataclass(frozen=True)
class RegionExpr:
    """Recursive boolean expression over deterministic 2D primitives."""

    op: RegionOp
    shape: RegionShape | None = None
    children: tuple[RegionExpr, ...] = ()
    base: RegionExpr | None = None
    subtract: tuple[RegionExpr, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.op, RegionOp):
            raise ModelValidationError("$.op", "must be a RegionOp")
        if self.op is RegionOp.SHAPE:
            if self.shape is None or self.children or self.base is not None or self.subtract:
                raise ModelValidationError("$", "shape expressions require only the shape field")
        elif self.op in (RegionOp.UNION, RegionOp.INTERSECTION):
            if not self.children:
                raise ModelValidationError("$.children", "must contain at least one region")
            if self.shape is not None or self.base is not None or self.subtract:
                raise ModelValidationError("$", f"{self.op.value} expressions require only children")
        elif self.op is RegionOp.DIFFERENCE:
            if self.base is None:
                raise ModelValidationError("$.base", "is required")
            if not self.subtract:
                raise ModelValidationError("$.subtract", "must contain at least one region")
            if self.shape is not None or self.children:
                raise ModelValidationError("$", "difference expressions require only base and subtract")

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> RegionExpr:
        """Decode a strict JSON-compatible RegionExpr tree."""
        data = _expect_mapping(value, path)
        op_value = data.get("op")
        if not isinstance(op_value, str):
            raise ModelValidationError(f"{path}.op", "must be a string")
        try:
            op = RegionOp(op_value)
        except ValueError as exc:
            choices = ", ".join(item.value for item in RegionOp)
            raise ModelValidationError(f"{path}.op", f"must be one of: {choices}") from exc

        if op is RegionOp.SHAPE:
            _check_fields(data, required={"op", "shape"}, path=path)
            return cls(op=op, shape=_shape_from_dict(data["shape"], f"{path}.shape"))
        if op in (RegionOp.UNION, RegionOp.INTERSECTION):
            _check_fields(data, required={"op", "children"}, path=path)
            raw_children = _expect_sequence(data["children"], f"{path}.children")
            if not raw_children:
                raise ModelValidationError(f"{path}.children", "must contain at least one region")
            children = tuple(
                cls.from_dict(child, path=f"{path}.children[{index}]") for index, child in enumerate(raw_children)
            )
            return cls(op=op, children=children)

        _check_fields(data, required={"op", "base", "subtract"}, path=path)
        raw_subtract = _expect_sequence(data["subtract"], f"{path}.subtract")
        if not raw_subtract:
            raise ModelValidationError(f"{path}.subtract", "must contain at least one region")
        base = cls.from_dict(data["base"], path=f"{path}.base")
        subtract = tuple(
            cls.from_dict(child, path=f"{path}.subtract[{index}]") for index, child in enumerate(raw_subtract)
        )
        return cls(op=op, base=base, subtract=subtract)

    @classmethod
    def from_shape(cls, shape: RegionShape) -> RegionExpr:
        return cls(op=RegionOp.SHAPE, shape=shape)

    @classmethod
    def union(cls, *children: RegionExpr) -> RegionExpr:
        return cls(op=RegionOp.UNION, children=tuple(children))

    @classmethod
    def intersection(cls, *children: RegionExpr) -> RegionExpr:
        return cls(op=RegionOp.INTERSECTION, children=tuple(children))

    @classmethod
    def difference(cls, base: RegionExpr, *subtract: RegionExpr) -> RegionExpr:
        return cls(op=RegionOp.DIFFERENCE, base=base, subtract=tuple(subtract))

    def contains(self, x: float, z: float) -> bool:
        """Return whether the point is in this region, including primitive boundaries."""
        if self.op is RegionOp.SHAPE:
            assert self.shape is not None
            return self.shape.contains(x, z)
        if self.op is RegionOp.UNION:
            return any(child.contains(x, z) for child in self.children)
        if self.op is RegionOp.INTERSECTION:
            return all(child.contains(x, z) for child in self.children)
        assert self.base is not None
        return self.base.contains(x, z) and not any(child.contains(x, z) for child in self.subtract)

    def bounds(self) -> Bounds2D | None:
        """Return a conservative inclusive integer envelope, or ``None`` if provably empty."""
        if self.op is RegionOp.SHAPE:
            assert self.shape is not None
            return self.shape.bounds()
        if self.op is RegionOp.UNION:
            child_bounds = [bounds for child in self.children if (bounds := child.bounds()) is not None]
            if not child_bounds:
                return None
            return (
                min(bounds[0] for bounds in child_bounds),
                max(bounds[1] for bounds in child_bounds),
                min(bounds[2] for bounds in child_bounds),
                max(bounds[3] for bounds in child_bounds),
            )
        if self.op is RegionOp.INTERSECTION:
            result = self.children[0].bounds()
            for child in self.children[1:]:
                child_bounds = child.bounds()
                if result is None or child_bounds is None:
                    return None
                result = _intersect_bounds(result, child_bounds)
            return result
        assert self.base is not None
        return self.base.bounds()

    def iter_cells(self, bounds: Bounds2D | None = None) -> Iterator[Cell2D]:
        """Yield contained integer cells in x-major, then z-major, deterministic order."""
        envelope = self.bounds() if bounds is None else bounds
        if envelope is None:
            return
        min_x, max_x, min_z, max_z = envelope
        for x in range(min_x, max_x + 1):
            for z in range(min_z, max_z + 1):
                if self.contains(x, z):
                    yield x, z

    def rasterize(self, bounds: Bounds2D | None = None) -> set[Cell2D]:
        """Return the set of integer cells contained by the expression."""
        return set(self.iter_cells(bounds))

    def to_dict(self) -> dict[str, Any]:
        if self.op is RegionOp.SHAPE:
            assert self.shape is not None
            return {"op": self.op.value, "shape": self.shape.to_dict()}
        if self.op in (RegionOp.UNION, RegionOp.INTERSECTION):
            return {"op": self.op.value, "children": [child.to_dict() for child in self.children]}
        assert self.base is not None
        return {
            "op": self.op.value,
            "base": self.base.to_dict(),
            "subtract": [child.to_dict() for child in self.subtract],
        }
