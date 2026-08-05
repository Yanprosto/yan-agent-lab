"""Artifact paths for a multi-component project run.

``ProjectRunDir`` deliberately wraps, rather than extends, :class:`mcbuild.rundir.RunDir`.
The existing agent owns its flat artifact layout; each project component therefore gets a
separate ``RunDir`` rooted below ``components/`` so worker sessions cannot overwrite one
another or the planner artifacts.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from mcbuild.rundir import RunDir, slugify

_SAFE_ID = re.compile(r"[a-z][a-z0-9_]*\Z")


@dataclass(frozen=True)
class ProjectRunDir:
    """Own and validate the complete artifact tree for one project run."""

    root: Path

    def __post_init__(self) -> None:
        root = Path(self.root)
        root.mkdir(parents=True, exist_ok=True)
        object.__setattr__(self, "root", root)

    @classmethod
    def create(cls, prompt: str, base: str | Path = "runs") -> ProjectRunDir:
        """Create a collision-safe ``runs/<timestamp>-<slug>`` directory."""

        base_path = Path(base)
        base_path.mkdir(parents=True, exist_ok=True)
        stem = f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(prompt)}"
        for suffix in range(1000):
            name = stem if suffix == 0 else f"{stem}-{suffix + 1:02d}"
            root = base_path / name
            try:
                root.mkdir(parents=False, exist_ok=False)
            except FileExistsError:
                continue
            rundir = cls(root)
            rundir.write_text("prompt.txt", prompt)
            return rundir
        raise RuntimeError(f"Could not allocate a unique project run directory below {base_path}")

    def _path_below(self, base: Path, name: str | Path) -> Path:
        relative = Path(name)
        if relative.is_absolute() or not relative.parts:
            raise ValueError(f"Artifact path must be a non-empty relative path: {name!s}")
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError(f"Unsafe artifact path: {name!s}")

        base_resolved = base.resolve()
        result = (base / relative).resolve()
        if not result.is_relative_to(base_resolved):
            raise ValueError(f"Artifact path escapes the project run directory: {name!s}")
        result.parent.mkdir(parents=True, exist_ok=True)
        return result

    def path(self, name: str | Path) -> Path:
        """Return a path below the run root, creating parent directories."""

        return self._path_below(self.root, name)

    def project_path(self, name: str | Path) -> Path:
        """Return a path below the planner's isolated ``project/`` directory."""

        return self._path_below(self.root / "project", name)

    def component_dir(self, index: int, package_id: str) -> Path:
        """Return ``components/NN_<id>`` after validating its stable identifier."""

        if index < 1:
            raise ValueError("Component index must be 1 or greater")
        if not _SAFE_ID.fullmatch(package_id):
            raise ValueError(f"Unsafe work package id: {package_id!r}")
        directory = self._path_below(self.root / "components", f"{index:02d}_{package_id}")
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def component_rundir(self, index: int, package_id: str) -> RunDir:
        """Create an existing-agent ``RunDir`` isolated to one work package."""

        return RunDir(self.component_dir(index, package_id))

    def merge_report_path(self, index: int) -> Path:
        """Return the stable path for one component's merge report."""

        if index < 1:
            raise ValueError("Component index must be 1 or greater")
        return self._path_below(self.root / "merge_reports", f"component_{index:02d}.json")

    def write_text(self, name: str | Path, content: str) -> Path:
        path = self.path(name)
        path.write_text(content, encoding="utf-8")
        return path

    def write_bytes(self, name: str | Path, content: bytes) -> Path:
        path = self.path(name)
        path.write_bytes(content)
        return path

    def write_json(self, name: str | Path, data: Any) -> Path:
        """Write strict JSON; unsupported runtime objects are errors, not strings."""

        return self.write_text(name, json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    def append_jsonl(self, name: str | Path, record: dict[str, Any]) -> Path:
        path = self.path(name)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def save_image(self, name: str | Path, image: Image.Image) -> Path:
        path = self.path(name)
        image.save(path, format="PNG")
        return path

    def write_project_json(self, name: str | Path, data: Any) -> Path:
        path = self.project_path(name)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return path

    def save_project_image(self, name: str | Path, image: Image.Image) -> Path:
        path = self.project_path(name)
        image.save(path, format="PNG")
        return path
