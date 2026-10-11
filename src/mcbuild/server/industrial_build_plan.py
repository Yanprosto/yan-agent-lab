"""Compile architecture decisions into executable cells and physical handoff edges."""

from dataclasses import dataclass

from mcbuild.server.industrial_planner import IronWorksCandidate
from mcbuild.server.mission_session import FactoryLayout, _layout
from mcbuild.server.process_plans import ProcessStage


@dataclass(frozen=True)
class PlannedCell:
    id: str
    stage: ProcessStage
    layout: FactoryLayout
    upstream: str | None = None


@dataclass(frozen=True)
class IndustrialBuildPlan:
    candidate: IronWorksCandidate
    cells: tuple[PlannedCell, ...]

    @property
    def footprint(self):
        return tuple(dict.fromkeys(p for cell in self.cells for p in cell.layout.footprint))

    def as_dict(self):
        return {
            "candidate": self.candidate.as_dict(),
            "cells": [
                {
                    "id": c.id,
                    "machine": c.stage.machine_block,
                    "machines": c.stage.machines,
                    "upstream": c.upstream,
                    "input": [c.stage.input_item, c.stage.input_count],
                    "output": [c.stage.output_item, c.stage.output_count],
                    "source": c.layout.source.args(),
                    "sink": c.layout.sink.args(),
                    "footprint": [p.args() for p in c.layout.footprint],
                }
                for c in self.cells
            ],
        }


def compile_industrial_plan(candidate: IronWorksCandidate, dx=0, dz=0, spacing=10):
    if not candidate.verified_primitives_only:
        raise ValueError("unverified primitive")
    if spacing < 6:
        raise ValueError("insufficient lane clearance")
    lanes = candidate.smelting_cells
    if lanes < 1 or candidate.enrichment_cells != (0 if candidate.direct_smelting else lanes):
        raise ValueError("unsupported stage topology")
    if candidate.raw_input % lanes or candidate.final_output % lanes:
        raise ValueError("batch must split evenly across lanes")
    raw, final = candidate.raw_input // lanes, candidate.final_output // lanes
    if candidate.direct_smelting:
        if raw != final:
            raise ValueError("direct smelting balance mismatch")
    elif raw % 3 or final != raw // 3 * 4:
        raise ValueError("enrichment recipe balance mismatch")
    cells = []
    for lane in range(lanes):
        z = dz + lane * spacing
        upstream = None
        if not candidate.direct_smelting:
            upstream = f"lane-{lane}-enrich"
            cells.append(
                PlannedCell(
                    upstream,
                    ProcessStage(
                        upstream, "mekanism:enrichment_chamber", "minecraft:raw_iron", "mekanism:dust_iron", raw, final
                    ),
                    _layout(dx, z),
                )
            )
        cell_id = f"lane-{lane}-smelt"
        cells.append(
            PlannedCell(
                cell_id,
                ProcessStage(
                    cell_id,
                    "mekanism:energized_smelter",
                    "minecraft:raw_iron" if candidate.direct_smelting else "mekanism:dust_iron",
                    "minecraft:iron_ingot",
                    raw if candidate.direct_smelting else final,
                    final,
                ),
                _layout(dx + (0 if candidate.direct_smelting else 8), z),
                upstream,
            )
        )
    plan = IndustrialBuildPlan(candidate, tuple(cells))
    owners = {}
    by_id = {c.id: c for c in cells}
    for cell in cells:
        if cell.upstream and by_id[cell.upstream].layout.sink != cell.layout.source:
            raise ValueError("disconnected stage handoff")
        for p in cell.layout.footprint:
            if p in owners:
                previous = owners[p]
                if cell.upstream != previous.id or p != cell.layout.source or p != previous.layout.sink:
                    raise ValueError(f"cell collision at {p}")
            owners[p] = cell
    return plan
