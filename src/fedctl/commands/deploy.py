from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

from fedctl.deploy import naming
from fedctl.deploy.render import RenderedJobs, render_deploy
from fedctl.deploy.spec import default_deploy_spec

console = Console()


def run_deploy(
    *,
    dry_run: bool = False,
    out: str | None = None,
    fmt: str = "json",
    num_supernodes: int = 2,
) -> int:
    if not dry_run:
        console.print("[red]✗ Deploy submission not implemented.[/red] Use --dry-run.")
        return 1

    if fmt != "json":
        console.print(f"[red]✗ Unsupported format:[/red] {fmt}")
        return 1

    spec = default_deploy_spec(num_supernodes=num_supernodes)
    try:
        rendered = render_deploy(spec)
    except Exception as exc:
        console.print(f"[red]✗ Render error:[/red] {exc}")
        return 1

    if out:
        _write_rendered(Path(out), rendered)
        console.print(f"[green]✓ Rendered jobs to:[/green] {out}")
        return 0

    bundle = _bundle_json(rendered)
    print(json.dumps(bundle, indent=2, sort_keys=True))
    return 0


def _bundle_json(rendered: RenderedJobs) -> dict[str, object]:
    return {
        naming.job_superlink(): rendered.superlink,
        naming.job_supernodes(): rendered.supernodes,
        naming.job_superexec_serverapp(): rendered.superexec_serverapp,
        "superexec-clientapps": rendered.superexec_clientapps,
    }


def _write_rendered(out_dir: Path, rendered: RenderedJobs) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_job(out_dir / f"{naming.job_superlink()}.json", rendered.superlink)
    _write_job(out_dir / f"{naming.job_supernodes()}.json", rendered.supernodes)
    _write_job(out_dir / f"{naming.job_superexec_serverapp()}.json", rendered.superexec_serverapp)
    for job in rendered.superexec_clientapps:
        name = job.get("Job", {}).get("Name")
        if isinstance(name, str) and name:
            _write_job(out_dir / f"{name}.json", job)


def _write_job(path: Path, job: dict[str, object]) -> None:
    path.write_text(json.dumps(job, indent=2, sort_keys=True), encoding="utf-8")
