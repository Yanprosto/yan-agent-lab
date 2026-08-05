"""Strict, JSON-round-trippable contracts for multi-component projects."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from enum import Enum, StrEnum
from typing import TYPE_CHECKING, Any

from mcbuild.config import Config
from mcbuild.orchestrator.region import Bounds2D, ModelValidationError, RegionExpr

if TYPE_CHECKING:
    from mcbuild.llm.client import Usage
    from mcbuild.voxel import VoxelGrid

ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SUPPORTED_SCHEMA_VERSION = 1
SUPPORTED_INSTANCE_ROTATIONS = frozenset({0, 90, 180, 270})
MAX_REQUESTED_VIEWS = 8

StyleValue = str | list[str]


class BoundaryKind(StrEnum):
    HARD = "hard"
    SOFT = "soft"


class WritePolicy(StrEnum):
    PRESERVE_EXISTING = "preserve_existing"
    ADDITIVE = "additive"
    OVERWRITE = "overwrite"
    CARVE = "carve"


class MergePolicy(StrEnum):
    PRESERVE_EXISTING = "preserve_existing"


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelValidationError(path, "must be an object")
    if not all(isinstance(key, str) for key in value):
        raise ModelValidationError(path, "object keys must be strings")
    return value


def _fields(
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


def _string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ModelValidationError(path, "must be a string")
    if not allow_empty and not value.strip():
        raise ModelValidationError(path, "must not be empty")
    return value


def _identifier(value: Any, path: str) -> str:
    identifier = _string(value, path)
    if ID_PATTERN.fullmatch(identifier) is None:
        raise ModelValidationError(path, "must match [a-z][a-z0-9_]*")
    return identifier


def _integer(value: Any, path: str) -> int:
    if type(value) is not int:
        raise ModelValidationError(path, "must be an integer")
    return value


def _finite_float(value: Any, path: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise ModelValidationError(path, "must be a finite number")
    return float(value)


def _array(value: Any, path: str) -> Sequence[Any]:
    if not isinstance(value, (list, tuple)):
        raise ModelValidationError(path, "must be an array")
    return value


def _string_list(value: Any, path: str, *, nonempty: bool = False, identifiers: bool = False) -> list[str]:
    raw = _array(value, path)
    if nonempty and not raw:
        raise ModelValidationError(path, "must contain at least one item")
    parse = _identifier if identifiers else _string
    return [parse(item, f"{path}[{index}]") for index, item in enumerate(raw)]


def _enum(value: Any, enum_type: type[Enum], path: str) -> Any:
    if not isinstance(value, str):
        raise ModelValidationError(path, "must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        choices = ", ".join(str(item.value) for item in enum_type)
        raise ModelValidationError(path, f"must be one of: {choices}") from exc


def _validate_identifier(identifier: str, path: str) -> None:
    _identifier(identifier, path)


def _validate_string(value: str, path: str, *, allow_empty: bool = False) -> None:
    _string(value, path, allow_empty=allow_empty)


def _parse_style_value(value: Any, path: str) -> StyleValue:
    if isinstance(value, str):
        return _string(value, path)
    return _string_list(value, path, nonempty=True)


@dataclass(frozen=True)
class Site:
    min_x: int
    max_x: int
    min_z: int
    max_z: int
    base_y: int

    def __post_init__(self) -> None:
        for name in ("min_x", "max_x", "min_z", "max_z", "base_y"):
            _integer(getattr(self, name), f"$.{name}")
        if self.min_x > self.max_x:
            raise ModelValidationError("$.min_x", "must be less than or equal to max_x")
        if self.min_z > self.max_z:
            raise ModelValidationError("$.min_z", "must be less than or equal to max_z")

    def contains(self, x: int | float, z: int | float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_z <= z <= self.max_z

    @property
    def bounds(self) -> Bounds2D:
        return self.min_x, self.max_x, self.min_z, self.max_z

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> Site:
        data = _mapping(value, path)
        required = {"min_x", "max_x", "min_z", "max_z", "base_y"}
        _fields(data, required=required, path=path)
        values = {name: _integer(data[name], f"{path}.{name}") for name in required}
        if values["min_x"] > values["max_x"]:
            raise ModelValidationError(f"{path}.min_x", "must be less than or equal to max_x")
        if values["min_z"] > values["max_z"]:
            raise ModelValidationError(f"{path}.min_z", "must be less than or equal to max_z")
        return cls(**values)

    def to_dict(self) -> dict[str, int]:
        return {
            "min_x": self.min_x,
            "max_x": self.max_x,
            "min_z": self.min_z,
            "max_z": self.max_z,
            "base_y": self.base_y,
        }


@dataclass
class StyleBible:
    architectural_style: StyleValue
    scale_and_massing: StyleValue
    primary_palette: StyleValue
    secondary_palette: StyleValue
    accent_palette: StyleValue
    roof_language: StyleValue
    opening_language: StyleValue
    detail_language: StyleValue
    landscape_language: StyleValue
    global_constraints: StyleValue

    FIELD_NAMES = (
        "architectural_style",
        "scale_and_massing",
        "primary_palette",
        "secondary_palette",
        "accent_palette",
        "roof_language",
        "opening_language",
        "detail_language",
        "landscape_language",
        "global_constraints",
    )

    def __post_init__(self) -> None:
        for name in self.FIELD_NAMES:
            value = getattr(self, name)
            parsed = _parse_style_value(value, f"$.{name}")
            if isinstance(parsed, list):
                setattr(self, name, list(parsed))

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> StyleBible:
        data = _mapping(value, path)
        required = set(cls.FIELD_NAMES)
        _fields(data, required=required, path=path)
        return cls(**{name: _parse_style_value(data[name], f"{path}.{name}") for name in cls.FIELD_NAMES})

    def to_dict(self) -> dict[str, StyleValue]:
        result: dict[str, StyleValue] = {}
        for name in self.FIELD_NAMES:
            value: StyleValue = getattr(self, name)
            result[name] = list(value) if isinstance(value, list) else value
        return result


@dataclass(frozen=True)
class Instance:
    id: str
    anchor: tuple[int, int, int]
    rotation: int

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "$.id")
        if len(self.anchor) != 3:
            raise ModelValidationError("$.anchor", "must contain exactly three coordinates")
        for index, coordinate in enumerate(self.anchor):
            _integer(coordinate, f"$.anchor[{index}]")
        if type(self.rotation) is not int or self.rotation not in SUPPORTED_INSTANCE_ROTATIONS:
            raise ModelValidationError("$.rotation", "must be one of: 0, 90, 180, 270")

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> Instance:
        data = _mapping(value, path)
        _fields(data, required={"id", "anchor", "rotation"}, path=path)
        raw_anchor = _array(data["anchor"], f"{path}.anchor")
        if len(raw_anchor) != 3:
            raise ModelValidationError(f"{path}.anchor", "must contain exactly three coordinates")
        anchor = (
            _integer(raw_anchor[0], f"{path}.anchor[0]"),
            _integer(raw_anchor[1], f"{path}.anchor[1]"),
            _integer(raw_anchor[2], f"{path}.anchor[2]"),
        )
        rotation = _integer(data["rotation"], f"{path}.rotation")
        if rotation not in SUPPORTED_INSTANCE_ROTATIONS:
            raise ModelValidationError(f"{path}.rotation", "must be one of: 0, 90, 180, 270")
        return cls(id=_identifier(data["id"], f"{path}.id"), anchor=anchor, rotation=rotation)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "anchor": list(self.anchor), "rotation": self.rotation}


@dataclass(frozen=True)
class Responsibility:
    """A 2.5D write responsibility: planar core/halo plus an inclusive y range."""

    boundary_kind: BoundaryKind
    core: RegionExpr
    min_y: int
    max_y: int
    halo: RegionExpr | None = None
    write_policy: WritePolicy = WritePolicy.PRESERVE_EXISTING

    def __post_init__(self) -> None:
        if not isinstance(self.boundary_kind, BoundaryKind):
            raise ModelValidationError("$.boundary_kind", "must be a BoundaryKind")
        if not isinstance(self.core, RegionExpr):
            raise ModelValidationError("$.core", "must be a RegionExpr")
        if self.halo is not None and not isinstance(self.halo, RegionExpr):
            raise ModelValidationError("$.halo", "must be a RegionExpr or null")
        _integer(self.min_y, "$.min_y")
        _integer(self.max_y, "$.max_y")
        if self.min_y > self.max_y:
            raise ModelValidationError("$.min_y", "must be less than or equal to max_y")
        if not isinstance(self.write_policy, WritePolicy):
            raise ModelValidationError("$.write_policy", "must be a WritePolicy")
        if self.boundary_kind is BoundaryKind.HARD and self.halo is not None:
            raise ModelValidationError("$.halo", "hard responsibilities cannot define a halo")

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> Responsibility:
        data = _mapping(value, path)
        required = {"boundary_kind", "core", "min_y", "max_y"}
        optional = {"halo", "write_policy"}
        _fields(data, required=required, optional=optional, path=path)
        boundary_kind = _enum(data["boundary_kind"], BoundaryKind, f"{path}.boundary_kind")
        halo_value = data.get("halo")
        if boundary_kind is BoundaryKind.HARD and halo_value is not None:
            raise ModelValidationError(f"{path}.halo", "hard responsibilities cannot define a halo")
        min_y = _integer(data["min_y"], f"{path}.min_y")
        max_y = _integer(data["max_y"], f"{path}.max_y")
        if min_y > max_y:
            raise ModelValidationError(f"{path}.min_y", "must be less than or equal to max_y")
        return cls(
            boundary_kind=boundary_kind,
            core=RegionExpr.from_dict(data["core"], path=f"{path}.core"),
            min_y=min_y,
            max_y=max_y,
            halo=RegionExpr.from_dict(halo_value, path=f"{path}.halo") if halo_value is not None else None,
            write_policy=_enum(
                data.get("write_policy", WritePolicy.PRESERVE_EXISTING.value),
                WritePolicy,
                f"{path}.write_policy",
            ),
        )

    def contains(self, x: float, y: float, z: float, *, include_halo: bool = False) -> bool:
        if not self.min_y <= y <= self.max_y:
            return False
        if self.core.contains(x, z):
            return True
        return bool(include_halo and self.halo is not None and self.halo.contains(x, z))

    def planar_contains(self, x: float, z: float, *, include_halo: bool = False) -> bool:
        return self.core.contains(x, z) or bool(include_halo and self.halo is not None and self.halo.contains(x, z))

    def allowed_bounds(self) -> Bounds2D | None:
        core_bounds = self.core.bounds()
        if self.boundary_kind is BoundaryKind.HARD or self.halo is None:
            return core_bounds
        halo_bounds = self.halo.bounds()
        if core_bounds is None:
            return halo_bounds
        if halo_bounds is None:
            return core_bounds
        return (
            min(core_bounds[0], halo_bounds[0]),
            max(core_bounds[1], halo_bounds[1]),
            min(core_bounds[2], halo_bounds[2]),
            max(core_bounds[3], halo_bounds[3]),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary_kind": self.boundary_kind.value,
            "core": self.core.to_dict(),
            "halo": self.halo.to_dict() if self.halo is not None else None,
            "min_y": self.min_y,
            "max_y": self.max_y,
            "write_policy": self.write_policy.value,
        }


def _normalize_view(value: Any, path: str) -> dict[str, Any]:
    data = _mapping(value, path)
    allowed = {"mode", "yaw", "cutaway", "slice_axis", "slice_at"}
    _fields(data, required=set(), optional=allowed, path=path)
    mode = data.get("mode", "iso")
    if not isinstance(mode, str) or mode not in ("iso", "top-down"):
        raise ModelValidationError(f"{path}.mode", "must be 'iso' or 'top-down'")
    if mode == "top-down":
        extra = sorted(key for key in data if key != "mode")
        if extra:
            raise ModelValidationError(path, f"top-down views do not accept: {', '.join(extra)}")
        return {"mode": "top-down"}
    yaw = _integer(data.get("yaw", 0), f"{path}.yaw")
    if not 0 <= yaw <= 3:
        raise ModelValidationError(f"{path}.yaw", "must be between 0 and 3")
    cutaway = data.get("cutaway", "none")
    if not isinstance(cutaway, str) or cutaway not in ("none", "x", "z"):
        raise ModelValidationError(f"{path}.cutaway", "must be one of: none, x, z")
    slice_axis = data.get("slice_axis")
    slice_at = data.get("slice_at")
    if (slice_axis is None) != (slice_at is None):
        raise ModelValidationError(path, "slice_axis and slice_at must be provided together")
    if slice_axis is not None:
        if cutaway != "none":
            raise ModelValidationError(path, "cutaway and slice_axis/slice_at are mutually exclusive")
        if not isinstance(slice_axis, str) or slice_axis not in ("x", "y", "z"):
            raise ModelValidationError(f"{path}.slice_axis", "must be one of: x, y, z")
        slice_at = _integer(slice_at, f"{path}.slice_at")
    facing_yaws = {"x": (2, 3), "z": (1, 2)}
    cut_axis = slice_axis if slice_axis in facing_yaws else (cutaway if cutaway != "none" else None)
    if cut_axis is not None and yaw not in facing_yaws[cut_axis]:
        allowed_yaws = ", ".join(str(item) for item in facing_yaws[cut_axis])
        raise ModelValidationError(f"{path}.yaw", f"must be one of {allowed_yaws} when cutting on {cut_axis}")
    normalized: dict[str, Any] = {"yaw": yaw}
    if cutaway != "none":
        normalized["cutaway"] = cutaway
    if slice_axis is not None:
        normalized["slice_axis"] = slice_axis
        normalized["slice_at"] = slice_at
    return normalized


@dataclass
class WorkPackage:
    id: str
    name: str
    semantic_type: str
    objective: str
    instances: list[Instance]
    responsibility: Responsibility
    depends_on: list[str]
    neighbor_context: list[str]
    worker_brief: str
    acceptance_criteria: list[str]
    requested_views: list[dict[str, Any]]

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "$.id")
        for name in ("name", "semantic_type", "objective", "worker_brief"):
            _validate_string(getattr(self, name), f"$.{name}")
        if not self.instances:
            raise ModelValidationError("$.instances", "must contain at least one instance")
        if not all(isinstance(item, Instance) for item in self.instances):
            raise ModelValidationError("$.instances", "must contain Instance objects")
        if not isinstance(self.responsibility, Responsibility):
            raise ModelValidationError("$.responsibility", "must be a Responsibility")
        self.depends_on = _string_list(self.depends_on, "$.depends_on", identifiers=True)
        self.neighbor_context = _string_list(self.neighbor_context, "$.neighbor_context")
        self.acceptance_criteria = _string_list(self.acceptance_criteria, "$.acceptance_criteria", nonempty=True)
        raw_views = _array(self.requested_views, "$.requested_views")
        if not 1 <= len(raw_views) <= MAX_REQUESTED_VIEWS:
            raise ModelValidationError("$.requested_views", f"must contain 1-{MAX_REQUESTED_VIEWS} views")
        self.instances = list(self.instances)
        self.requested_views = [
            _normalize_view(view, f"$.requested_views[{index}]") for index, view in enumerate(raw_views)
        ]

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> WorkPackage:
        data = _mapping(value, path)
        required = {
            "id",
            "name",
            "semantic_type",
            "objective",
            "instances",
            "responsibility",
            "depends_on",
            "neighbor_context",
            "worker_brief",
            "acceptance_criteria",
            "requested_views",
        }
        _fields(data, required=required, path=path)
        raw_instances = _array(data["instances"], f"{path}.instances")
        if not raw_instances:
            raise ModelValidationError(f"{path}.instances", "must contain at least one instance")
        raw_views = _array(data["requested_views"], f"{path}.requested_views")
        if not 1 <= len(raw_views) <= MAX_REQUESTED_VIEWS:
            raise ModelValidationError(f"{path}.requested_views", f"must contain 1-{MAX_REQUESTED_VIEWS} views")
        return cls(
            id=_identifier(data["id"], f"{path}.id"),
            name=_string(data["name"], f"{path}.name"),
            semantic_type=_string(data["semantic_type"], f"{path}.semantic_type"),
            objective=_string(data["objective"], f"{path}.objective"),
            instances=[
                Instance.from_dict(item, path=f"{path}.instances[{index}]") for index, item in enumerate(raw_instances)
            ],
            responsibility=Responsibility.from_dict(data["responsibility"], path=f"{path}.responsibility"),
            depends_on=_string_list(data["depends_on"], f"{path}.depends_on", identifiers=True),
            neighbor_context=_string_list(data["neighbor_context"], f"{path}.neighbor_context"),
            worker_brief=_string(data["worker_brief"], f"{path}.worker_brief"),
            acceptance_criteria=_string_list(data["acceptance_criteria"], f"{path}.acceptance_criteria", nonempty=True),
            requested_views=[
                _normalize_view(item, f"{path}.requested_views[{index}]") for index, item in enumerate(raw_views)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "semantic_type": self.semantic_type,
            "objective": self.objective,
            "instances": [instance.to_dict() for instance in self.instances],
            "responsibility": self.responsibility.to_dict(),
            "depends_on": list(self.depends_on),
            "neighbor_context": list(self.neighbor_context),
            "worker_brief": self.worker_brief,
            "acceptance_criteria": list(self.acceptance_criteria),
            "requested_views": [dict(view) for view in self.requested_views],
        }


@dataclass(frozen=True)
class InterfaceZone:
    id: str
    participants: tuple[str, str]
    region: RegionExpr
    description: str
    merge_policy: MergePolicy = MergePolicy.PRESERVE_EXISTING

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "$.id")
        if len(self.participants) != 2:
            raise ModelValidationError("$.participants", "must contain exactly two work package ids")
        for index, participant in enumerate(self.participants):
            _validate_identifier(participant, f"$.participants[{index}]")
        if self.participants[0] == self.participants[1]:
            raise ModelValidationError("$.participants", "must contain two distinct work package ids")
        if not isinstance(self.region, RegionExpr):
            raise ModelValidationError("$.region", "must be a RegionExpr")
        _validate_string(self.description, "$.description")
        if not isinstance(self.merge_policy, MergePolicy):
            raise ModelValidationError("$.merge_policy", "must be a MergePolicy")

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> InterfaceZone:
        data = _mapping(value, path)
        required = {"id", "participants", "region", "description", "merge_policy"}
        _fields(data, required=required, path=path)
        raw_participants = _array(data["participants"], f"{path}.participants")
        if len(raw_participants) != 2:
            raise ModelValidationError(f"{path}.participants", "must contain exactly two work package ids")
        participants = (
            _identifier(raw_participants[0], f"{path}.participants[0]"),
            _identifier(raw_participants[1], f"{path}.participants[1]"),
        )
        if participants[0] == participants[1]:
            raise ModelValidationError(f"{path}.participants", "must contain two distinct work package ids")
        return cls(
            id=_identifier(data["id"], f"{path}.id"),
            participants=participants,
            region=RegionExpr.from_dict(data["region"], path=f"{path}.region"),
            description=_string(data["description"], f"{path}.description"),
            merge_policy=_enum(data["merge_policy"], MergePolicy, f"{path}.merge_policy"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "participants": list(self.participants),
            "region": self.region.to_dict(),
            "description": self.description,
            "merge_policy": self.merge_policy.value,
        }


@dataclass
class ProjectPlan:
    schema_version: int
    title: str
    project_summary: str
    site: Site
    style_bible: StyleBible
    work_packages: list[WorkPackage]
    interfaces: list[InterfaceZone]

    def __post_init__(self) -> None:
        _integer(self.schema_version, "$.schema_version")
        if self.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ModelValidationError("$.schema_version", f"must equal {SUPPORTED_SCHEMA_VERSION}")
        _validate_string(self.title, "$.title")
        _validate_string(self.project_summary, "$.project_summary")
        if not isinstance(self.site, Site):
            raise ModelValidationError("$.site", "must be a Site")
        if not isinstance(self.style_bible, StyleBible):
            raise ModelValidationError("$.style_bible", "must be a StyleBible")
        if not self.work_packages:
            raise ModelValidationError("$.work_packages", "must contain at least one work package")
        if not all(isinstance(item, WorkPackage) for item in self.work_packages):
            raise ModelValidationError("$.work_packages", "must contain WorkPackage objects")
        if not all(isinstance(item, InterfaceZone) for item in self.interfaces):
            raise ModelValidationError("$.interfaces", "must contain InterfaceZone objects")
        self.work_packages = list(self.work_packages)
        self.interfaces = list(self.interfaces)

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> ProjectPlan:
        data = _mapping(value, path)
        required = {
            "schema_version",
            "title",
            "project_summary",
            "site",
            "style_bible",
            "work_packages",
            "interfaces",
        }
        _fields(data, required=required, path=path)
        schema_version = _integer(data["schema_version"], f"{path}.schema_version")
        if schema_version != SUPPORTED_SCHEMA_VERSION:
            raise ModelValidationError(f"{path}.schema_version", f"must equal {SUPPORTED_SCHEMA_VERSION}")
        raw_packages = _array(data["work_packages"], f"{path}.work_packages")
        if not raw_packages:
            raise ModelValidationError(f"{path}.work_packages", "must contain at least one work package")
        raw_interfaces = _array(data["interfaces"], f"{path}.interfaces")
        return cls(
            schema_version=schema_version,
            title=_string(data["title"], f"{path}.title"),
            project_summary=_string(data["project_summary"], f"{path}.project_summary"),
            site=Site.from_dict(data["site"], path=f"{path}.site"),
            style_bible=StyleBible.from_dict(data["style_bible"], path=f"{path}.style_bible"),
            work_packages=[
                WorkPackage.from_dict(item, path=f"{path}.work_packages[{index}]")
                for index, item in enumerate(raw_packages)
            ],
            interfaces=[
                InterfaceZone.from_dict(item, path=f"{path}.interfaces[{index}]")
                for index, item in enumerate(raw_interfaces)
            ],
        )

    @property
    def work_package_map(self) -> dict[str, WorkPackage]:
        """Map ids to packages; duplicate ids retain the first plan entry."""
        result: dict[str, WorkPackage] = {}
        for package in self.work_packages:
            result.setdefault(package.id, package)
        return result

    def package_by_id(self, package_id: str) -> WorkPackage:
        try:
            return self.work_package_map[package_id]
        except KeyError as exc:
            raise KeyError(f"unknown work package id: {package_id}") from exc

    def interfaces_for(self, package_id: str) -> list[InterfaceZone]:
        return [zone for zone in self.interfaces if package_id in zone.participants]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "project_summary": self.project_summary,
            "site": self.site.to_dict(),
            "style_bible": self.style_bible.to_dict(),
            "work_packages": [package.to_dict() for package in self.work_packages],
            "interfaces": [zone.to_dict() for zone in self.interfaces],
        }


@dataclass
class ProjectConfig:
    """Project-only configuration layered around an unchanged worker ``Config``."""

    worker_config: Config
    planner_model: str
    planner_max_iters: int = 3
    max_components: int = 8
    cost_ceiling: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.worker_config, Config):
            raise ModelValidationError("$.worker_config", "must be a Config")
        _validate_string(self.planner_model, "$.planner_model")
        _integer(self.planner_max_iters, "$.planner_max_iters")
        _integer(self.max_components, "$.max_components")
        if self.planner_max_iters <= 0:
            raise ModelValidationError("$.planner_max_iters", "must be greater than zero")
        if self.max_components <= 0:
            raise ModelValidationError("$.max_components", "must be greater than zero")
        if self.cost_ceiling is not None:
            self.cost_ceiling = _finite_float(self.cost_ceiling, "$.cost_ceiling")
            if self.cost_ceiling < 0:
                raise ModelValidationError("$.cost_ceiling", "must be non-negative")

    @classmethod
    def from_dict(cls, value: Any, *, path: str = "$") -> ProjectConfig:
        data = _mapping(value, path)
        _fields(
            data,
            required={"worker_config", "planner_model"},
            optional={"planner_max_iters", "max_components", "cost_ceiling"},
            path=path,
        )
        worker_data = _mapping(data["worker_config"], f"{path}.worker_config")
        config_fields = {field.name for field in fields(Config)}
        _fields(worker_data, required=set(), optional=config_fields, path=f"{path}.worker_config")
        worker_config = Config(**dict(worker_data))
        cost_value = data.get("cost_ceiling")
        cost_ceiling = _finite_float(cost_value, f"{path}.cost_ceiling") if cost_value is not None else None
        return cls(
            worker_config=worker_config,
            planner_model=_string(data["planner_model"], f"{path}.planner_model"),
            planner_max_iters=_integer(data.get("planner_max_iters", 3), f"{path}.planner_max_iters"),
            max_components=_integer(data.get("max_components", 8), f"{path}.max_components"),
            cost_ceiling=cost_ceiling,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "worker_config": {field.name: getattr(self.worker_config, field.name) for field in fields(Config)},
            "planner_model": self.planner_model,
            "planner_max_iters": self.planner_max_iters,
            "max_components": self.max_components,
            "cost_ceiling": self.cost_ceiling,
        }


@dataclass
class ProjectResult:
    """Serializable top-level outcome; the raw grid is summarized in ``to_dict``."""

    finished: bool
    summary: str
    plan: ProjectPlan | None
    grid: VoxelGrid | None
    completed_packages: list[str]
    failed_package: str | None
    validation_reports: list[Any]
    usage: Usage

    def to_dict(self) -> dict[str, Any]:
        grid_summary: dict[str, Any] | None = None
        if self.grid is not None:
            grid_summary = {"block_count": len(self.grid), "bounds": self.grid.bounds}
        reports = [report.to_dict() if hasattr(report, "to_dict") else report for report in self.validation_reports]
        return {
            "finished": self.finished,
            "summary": self.summary,
            "plan": self.plan.to_dict() if self.plan is not None else None,
            "grid": grid_summary,
            "completed_packages": list(self.completed_packages),
            "failed_package": self.failed_package,
            "validation_reports": reports,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "reasoning_tokens": self.usage.reasoning_tokens,
                "cached_tokens": self.usage.cached_tokens,
                "cost_usd": self.usage.cost_usd,
            },
        }
