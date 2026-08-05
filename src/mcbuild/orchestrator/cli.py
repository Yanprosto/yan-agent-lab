"""Independent ``mcbuild-project`` command-line entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer
from dotenv import load_dotenv
from PIL import Image
from rich.console import Console
from rich.panel import Panel

from mcbuild.config import Config
from mcbuild.llm.client import OpenRouterClient
from mcbuild.orchestrator.fake import (
    FakeProjectPlannerLLM,
    fake_worker_llm_factory,
    fake_worker_runner,
)
from mcbuild.orchestrator.loop import run_project
from mcbuild.orchestrator.models import ProjectConfig, WorkPackage
from mcbuild.orchestrator.run_dir import ProjectRunDir
from mcbuild.render.sixel import encode_sixel, supports_sixel

app = typer.Typer(add_completion=False)
console = Console()


def _display_image(path: str, display: str) -> None:
    if display == "off":
        return
    mode = "sixel" if display == "auto" and supports_sixel() else display
    if mode == "auto":
        mode = "ansi"
    try:
        image = Image.open(path).convert("RGB")
        if mode == "sixel":
            image.thumbnail((800, 800))
            sys.stdout.write(encode_sixel(image) + "\n")
            sys.stdout.flush()
        elif mode == "ansi":
            from rich_pixels import Pixels

            image.thumbnail((100, 100))
            console.print(Pixels.from_image(image))
    except Exception:
        # Display is best effort and must not invalidate a successfully rendered plan.
        return


@app.command()
def project(
    prompt: str = typer.Argument(..., help="Natural-language description of a large project."),
    model: str = typer.Option(Config.model, "--model", help="Worker model id."),
    planner_model: str = typer.Option(Config.model, "--planner-model", help="Planner model id."),
    max_iters: int = typer.Option(Config.max_iters, "--max-iters", help="Edit budget per worker."),
    planner_max_iters: int = typer.Option(3, "--planner-max-iters", help="Maximum submitted plan versions."),
    max_components: int = typer.Option(8, "--max-components", help="Maximum semantic work packages."),
    seed: int = typer.Option(0, "--seed"),
    display: str = typer.Option("auto", "--display", help="auto|sixel|ansi|off"),
    out: str = typer.Option("runs", "--out"),
    reasoning: str = typer.Option("medium", "--reasoning", help="off|low|medium|high"),
    cost_ceiling: float | None = typer.Option(
        None,
        "--cost-ceiling",
        help="Global USD ceiling across the planner and every worker.",
    ),
    fake_llm: bool = typer.Option(
        False,
        "--fake-llm",
        help="Run the deterministic offline planner and workers without an API key.",
    ),
) -> None:
    """Plan and build a serial, multi-component Minecraft project."""

    load_dotenv()
    if display not in {"auto", "sixel", "ansi", "off"}:
        console.print("[red]--display must be one of auto, sixel, ansi, off.[/red]")
        raise typer.Exit(2)

    worker_config = Config(
        model=model,
        max_iters=max_iters,
        seed=seed,
        display=display,
        out_dir=out,
        reasoning=reasoning,
        cost_ceiling=cost_ceiling,
    )
    project_config = ProjectConfig(
        worker_config=worker_config,
        planner_model=planner_model,
        planner_max_iters=planner_max_iters,
        max_components=max_components,
        cost_ceiling=cost_ceiling,
    )
    rundir = ProjectRunDir.create(prompt, base=out)

    if fake_llm:
        planner_llm: Any = FakeProjectPlannerLLM()
        worker_factory = fake_worker_llm_factory
        worker_runner = fake_worker_runner
    else:
        try:
            planner_llm = OpenRouterClient()
        except RuntimeError as error:
            console.print(f"[red]{error}[/red]")
            raise typer.Exit(1) from error

        def worker_factory(package: WorkPackage) -> OpenRouterClient:
            del package
            return OpenRouterClient()

        worker_runner = None

    console.print(Panel(f"[bold]{prompt}[/bold]\nrun dir: {rundir.root}", title="mcbuild-project"))

    def on_event(event_type: str, data: dict[str, Any]) -> None:
        if event_type in {"plan_submitted", "plan_revised"}:
            action = "draft" if event_type == "plan_submitted" else "revision"
            console.print(f"[cyan]planning: {action} {data['version']}[/cyan]")
        elif event_type == "plan_validation":
            report = data["report"]
            status = "passed" if report.get("valid") else f"{len(report.get('errors', []))} error(s)"
            console.print(f"[cyan]planning: validation {status}[/cyan]")
        elif event_type == "plan_render":
            console.print(f"[green]plan render:[/green] {data['image_path']}")
            _display_image(data["image_path"], display)
        elif event_type == "plan_approved":
            console.print("[bold green]planning: approved[/bold green]")
        elif event_type == "component_start":
            console.print(f"[blue]component {data['index']}/{data['total']}:[/blue] {data['package_id']}")
        elif event_type == "component_patch_validation":
            report = data["report"]
            if report.get("clipped_voxels"):
                console.print(f"[yellow]{data['package_id']}: clipped {report['clipped_voxels']} voxel(s)[/yellow]")
        elif event_type == "component_merged":
            console.print(f"[green]merged {data['package_id']}:[/green] {data['block_count']:,} stored voxels")
        elif event_type == "project_abort":
            console.print(Panel(data["reason"], title="project aborted", border_style="red"))

    kwargs: dict[str, Any] = {}
    if worker_runner is not None:
        kwargs["worker_runner"] = worker_runner
    result = run_project(
        prompt,
        planner_llm,
        worker_factory,
        project_config,
        rundir,
        on_event=on_event,
        **kwargs,
    )

    usage = result.usage
    console.print(
        Panel(
            f"completed: {len(result.completed_packages)}/{len(result.plan.work_packages) if result.plan else 0}\n"
            f"stored voxels: {len(result.grid) if result.grid is not None else 0:,}\n"
            f"tokens: {usage.prompt_tokens} in / {usage.completion_tokens} out\n"
            f"cost: ${usage.cost_usd:.4f}",
            title="project result",
            border_style="green" if result.finished else "red",
        )
    )
    if result.finished:
        final_path = Path(rundir.root) / "final.schem"
        console.print(f"[bold green]Exported:[/bold green] {final_path}")
    else:
        raise typer.Exit(1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
