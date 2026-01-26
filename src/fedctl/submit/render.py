from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader


@dataclass(frozen=True)
class SubmitJobSpec:
    job_name: str
    node_class: str
    image: str
    artifact_url: str
    datacenter: str = "dc1"
    namespace: str = "default"
    artifact_dest: str = "/local/project"
    command: str = "python"
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    work_dir: str = "/local/project"
    priority: int = 50
    cpu: int = 1000
    memory_mb: int = 1024
    docker_socket: str | None = "/var/run/docker.sock"
    docker_socket_name: str = "docker-socket"


def render_submit_job(spec: SubmitJobSpec) -> dict[str, Any]:
    env = _template_env()
    context = {
        "job_name": spec.job_name,
        "datacenters": [spec.datacenter],
        "namespace": spec.namespace,
        "node_class": spec.node_class,
        "image": spec.image,
        "artifact_url": spec.artifact_url,
        "artifact_dest": spec.artifact_dest,
        "command": spec.command,
        "args": spec.args,
        "env": spec.env,
        "work_dir": spec.work_dir,
        "priority": spec.priority,
        "cpu": spec.cpu,
        "memory_mb": spec.memory_mb,
        "docker_socket": spec.docker_socket,
        "docker_socket_name": spec.docker_socket_name,
    }
    return _render_template(env, "submit_runner.json.j2", context)


def _template_env() -> Environment:
    template_root = Path(__file__).resolve().parents[3] / "templates" / "nomad"
    return Environment(loader=FileSystemLoader(str(template_root)), autoescape=False)


def _render_template(env: Environment, name: str, context: dict[str, Any]) -> dict[str, Any]:
    rendered = env.get_template(name).render(**context)
    try:
        return json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Template {name} rendered invalid JSON: {exc}") from exc
