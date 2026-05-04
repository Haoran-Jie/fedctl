from __future__ import annotations

from datetime import datetime
from html import escape
from pathlib import Path
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ansi2html import Ansi2HTMLConverter
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import SubmitConfig
from ..submissions_service import (
    cancel_submission_record,
    count_visible_submissions_for_ui,
    get_submission_or_404,
    is_cancellable,
    is_purgeable,
    list_visible_submissions_for_ui,
    purge_submission_record,
    register_bearer_token,
    resolve_submission_logs_detail,
    submission_stats_for_principal,
)
from ..ui_auth import current_ui_principal, login_via_token, logout

router = APIRouter(include_in_schema=False)

_TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

_STATUS_FILTERS = ["active", "completed", "failed", "cancelled", "all"]
_SUBMISSIONS_UI_DEFAULT_LIMIT = 100
_SUBMISSIONS_UI_MAX_LIMIT = 1000
_LOG_JOBS = [
    ("submit", "Submit"),
    ("superlink", "SuperLink"),
    ("supernodes", "Supernodes"),
    ("superexec_serverapp", "SuperExec serverapp"),
    ("superexec_clientapps", "SuperExec clientapps"),
]
_HELP_CONFIG_SECTIONS = [
    {
        "slug": "run-config",
        "title": "Run config",
        "summary": "Sectioned TOML that describes the workload, method, seed, and Flower run settings.",
        "subtitle": "Run settings passed to Flower",
        "description": (
            "A run config is a TOML file for workload, method, seed, and Flower run-config values. "
            "fedctl validates and flattens it into the run config used by the remote Flower run."
        ),
        "command": "fedctl submit run apps/fedctl_research --run-config path/to/run.toml",
        "snippet": (
            "[run]\n"
            "method = \"fedavg\"\n"
            "task = \"fashion_mnist_mlp\"\n"
            "seed = 1337\n\n"
            "[server]\n"
            "num-server-rounds = 3\n"
            "min-available-nodes = 4"
        ),
        "details": [
            "Use a run config when a run needs to be reproducible. The file describes what should be trained and how Flower should run it; it does not choose the submit service, registry, Nomad node placement, or cluster resources.",
            "fedctl reads the sectioned TOML, applies seed expansion and command-line overrides, then writes the normalized run config consumed by the submit runner. The remote runner ultimately invokes Flower with a concrete --run-config for one child run.",
            "For a normal Flower project, this file is optional. If it is omitted, fedctl can submit the project using the defaults already present in the Flower app, such as pyproject.toml and local-simulation.num-supernodes.",
        ],
        "flow": [
            "Read the TOML passed with --run-config.",
            "Expand seed sweeps into one submission per seed when the config declares multiple seeds.",
            "Apply --seed and --run-config-override values from the CLI.",
            "Flatten sectioned TOML into Flower-compatible run-config keys.",
            "Run the remote Flower app with one concrete normalized config.",
        ],
        "sections": [
            {
                "title": "Typical contents",
                "items": [
                    "Run identity: method, task, seed, dataset split, and naming metadata.",
                    "Server settings: rounds, aggregation method parameters, buffer size, or async method knobs.",
                    "Client settings: local epochs, batch size, learning rate, and model/data options.",
                    "Device-specific settings when the project wants rpi4/rpi5 behavior to differ.",
                ],
            },
            {
                "title": "Precedence",
                "items": [
                    "--run-config-override is for one-off edits and wins over file values.",
                    "--seed pins a single seed for the child run and wins over file seed defaults.",
                    "A seed sweep in the file is expanded before the remote Flower process starts.",
                ],
            },
            {
                "title": "What it does not control",
                "items": [
                    "It does not contain the submit-service bearer token.",
                    "It does not select the Docker registry or fedctl submit runner image.",
                    "It does not allocate Nomad resources or choose rpi4/rpi5 node counts.",
                ],
            },
        ],
        "examples": [
            {
                "title": "Submit with a run config",
                "body": "Use this when the project has a reusable TOML file for the run settings.",
                "command": (
                    "fedctl submit run apps/fedctl_research \\\n"
                    "  --run-config apps/fedctl_research/run_configs/smoke/compute_heterogeneity/fashion_mnist_mlp/fedavg.toml"
                ),
            },
            {
                "title": "Override one Flower run-config value",
                "body": "Use an override for a small temporary change without copying the run-config file.",
                "command": (
                    "fedctl submit run apps/fedctl_research \\\n"
                    "  --run-config apps/fedctl_research/run_configs/smoke/compute_heterogeneity/fashion_mnist_mlp/fedavg.toml \\\n"
                    "  --run-config-override num-server-rounds=5"
                ),
            },
        ],
        "notes": [
            "Use this for algorithm, dataset, seed, and training parameters.",
            "Sectioned TOML is normalized into Flower's flat --run-config input.",
            "Seed sweeps expand into separate submissions before Flower starts.",
            "Use --run-config-override for one-off value changes without copying the file.",
        ],
        "related_commands": ["submit run"],
    },
    {
        "slug": "deploy-config",
        "title": "Deploy config",
        "summary": "YAML that tells fedctl how to reach and use the CamMLSys submit/cluster environment.",
        "subtitle": "Execution environment used by fedctl",
        "description": (
            "A deploy config is YAML consumed by fedctl and the submit runner. It is not passed to Flower; "
            "it stores user credentials and optional overrides for the built-in CamMLSys service, image, registry, resource, placement, and network defaults."
        ),
        "command": "fedctl submit run apps/fedctl_research --deploy-config .fedctl/fedctl.yaml",
        "snippet": (
            "deploy:\n"
            "  superexec:\n"
            "    env: {}\n\n"
            "submit:\n"
            "  token: \"\"\n"
            "  user: \"alice\""
        ),
        "full_snippet": (
            "deploy:\n"
            "  image_registry: \"128.232.61.111:5000\"\n"
            "  supernodes:\n"
            "    rpi4: 2\n"
            "    rpi5: 2\n"
            "  superexec:\n"
            "    env:\n"
            "      WANDB_PROJECT: \"fedctl\"\n"
            "      WANDB_ENTITY: \"your-wandb-entity\"\n"
            "      WANDB_API_KEY: \"set-a-real-key-here\"\n"
            "  placement:\n"
            "    allow_oversubscribe: true\n"
            "    spread_across_hosts: true\n"
            "    prefer_spread_across_hosts: false\n"
            "  resources:\n"
            "    supernode:\n"
            "      default: { cpu: 1000, mem: 1024 }\n"
            "      rpi4: { cpu: 1000, mem: 1024 }\n"
            "      rpi5: { cpu: 1000, mem: 1024 }\n"
            "    superexec_clientapp: { cpu: 2000, mem: 2048 }\n"
            "    superexec_serverapp: { cpu: 2000, mem: 2048 }\n"
            "    superlink: { cpu: 1000, mem: 1024 }\n"
            "  network:\n"
            "    image: \"jiahborcn/netem:latest\"\n"
            "    default_profile: none\n"
            "    default_assignment: \"rpi5[*]=med,rpi4[*]=high\"\n"
            "    interface: eth0\n"
            "    apply:\n"
            "      superexec_serverapp: false\n"
            "      superexec_clientapp: false\n"
            "    profiles:\n"
            "      none: {}\n"
            "      low: { delay_ms: 0, jitter_ms: 0, loss_pct: 0, rate_mbit: 1000, rate_latency_ms: 0, rate_burst_kbit: 256 }\n"
            "      med: { delay_ms: 60, jitter_ms: 10, loss_pct: 1.0, rate_mbit: 50, rate_latency_ms: 50, rate_burst_kbit: 256 }\n"
            "      high: { delay_ms: 120, jitter_ms: 25, loss_pct: 2.5, rate_mbit: 20, rate_latency_ms: 50, rate_burst_kbit: 256 }\n"
            "    ingress_profiles:\n"
            "      slow_downlink: { delay_ms: 120, jitter_ms: 25, loss_pct: 2.5, rate_mbit: 20, rate_latency_ms: 50, rate_burst_kbit: 256 }\n"
            "    egress_profiles:\n"
            "      slow_uplink: { delay_ms: 120, jitter_ms: 25, loss_pct: 2.5, rate_mbit: 20, rate_latency_ms: 50, rate_burst_kbit: 256 }\n\n"
            "submit:\n"
            "  endpoint: \"http://fedctl.cl.cam.ac.uk\"\n"
            "  token: \"\"\n"
            "  user: \"alice\"\n"
            "  image: \"128.232.61.111:5000/fedctl-submit:latest\"\n"
            "  artifact_store: \"s3+presign://fedctl-submits/fedctl-submits\"\n\n"
            "# Legacy compatibility accepted for old files, but not preferred:\n"
            "# image_registry: \"128.232.61.111:5000\"\n"
            "# build:\n"
            "#   image_registry: \"128.232.61.111:5000\"\n"
            "# submit-service:\n"
            "#   image_registry: \"128.232.61.111:5000\""
        ),
        "details": [
            "Use a deploy config when you need to provide submit-service credentials or override how fedctl runs the project. Normal CamMLSys installs inherit the shared submit-service endpoint, artifact store, submit runner image, image registry, Nomad resource defaults, placement rules, and network impairment profiles from code defaults.",
            "The deploy config is consumed by the local CLI and the submit runner. Flower does not receive this file as run config; Flower only receives the normalized run config plus the project archive.",
            "Fresh installs create a CamMLSys-oriented default deploy config on first fedctl use. For most users, setup should be pip install fedctl, register a bearer token with fedctl submit register-token, then run fedctl submit run <project>.",
        ],
        "flow": [
            "Resolve the deploy config from --deploy-config, project .fedctl/fedctl.yaml, or the active user profile.",
            "Read submit.token, submit.user, and any advanced overrides supplied by the config.",
            "Use built-in CamMLSys defaults for the submit endpoint, artifact store, submit image, registry, resources, placement, and netem settings when omitted.",
            "Apply optional resource, placement, supernode, and network overrides while rendering Nomad jobs.",
            "Persist submit-service metadata so status, logs, results, and inventory commands can inspect the run.",
        ],
        "sections": [
            {
                "title": "Fresh-install setup",
                "items": [
                    "fedctl creates ~/.config/fedctl/config.toml and ~/.config/fedctl/deploy-default.yaml on first CLI use.",
                    "The generated deploy-default.yaml only contains user-editable credentials and optional SuperExec environment variables; CamMLSys endpoint/image/registry defaults come from fedctl itself.",
                    "The intentionally blank value is submit.token; populate it with fedctl submit register-token, set it in the file, or export FEDCTL_SUBMIT_TOKEN.",
                    "Interactive submit commands can prompt for a missing or invalid bearer token and persist it to the user deploy config.",
                ],
            },
            {
                "title": "Resolution order",
                "items": [
                    "--deploy-config is explicit and wins for that command.",
                    "A project-local .fedctl/fedctl.yaml can select a deploy config for the project.",
                    "The active user profile falls back to ~/.config/fedctl/deploy-default.yaml.",
                    "If an explicit or project-local deploy config omits submit.token, fedctl can still read the saved token from the active user profile deploy config.",
                    "The hidden legacy --repo-config spelling and legacy repo_config profile key remain accepted for old installs.",
                ],
            },
            {
                "title": "Important fields",
                "items": [
                    "submit.endpoint optionally overrides the built-in CamMLSys submit service API.",
                    "submit.token or FEDCTL_SUBMIT_TOKEN provides the bearer token; fedctl submit register-token can create and save this value for a user.",
                    "submit.image optionally overrides the built-in fedctl submit runner image.",
                    "deploy.image_registry optionally overrides the built-in CamMLSys registry.",
                    "deploy.supernodes is optional. If omitted, fedctl can fall back to the Flower project's local-simulation.num-supernodes unless overridden by CLI flags or a deploy preset.",
                ],
            },
        ],
        "field_groups": [
            {
                "title": "submit",
                "description": "Submit-service and artifact-upload settings used before Nomad deployment starts.",
                "fields": [
                    {
                        "path": "submit.endpoint",
                        "type": "URL",
                        "description": "Optional submit service API endpoint override. Omit for the built-in CamMLSys default, http://fedctl.cl.cam.ac.uk.",
                    },
                    {
                        "path": "submit.token",
                        "type": "string",
                        "description": "Bearer token for the submit service. It may be left blank when FEDCTL_SUBMIT_TOKEN is set, and fedctl submit register-token or interactive CLI auth can persist a token here for user config files.",
                    },
                    {
                        "path": "submit.user",
                        "type": "string",
                        "description": "User label attached to submissions. Fresh configs default this from FEDCTL_SUBMIT_USER, USER, LOGNAME, USERNAME, or the local login name.",
                    },
                    {
                        "path": "submit.image",
                        "type": "image",
                        "description": "Optional Docker image override for the fedctl submit runner job. Omit for the built-in CamMLSys default, 128.232.61.111:5000/fedctl-submit:latest.",
                    },
                    {
                        "path": "submit.artifact_store",
                        "type": "URI",
                        "description": "Optional artifact upload target override for the packaged project archive. Omit for the built-in CamMLSys presigned S3 artifact store.",
                    },
                ],
            },
            {
                "title": "deploy",
                "description": "Cluster execution defaults consumed by fedctl and the remote submit runner.",
                "fields": [
                    {
                        "path": "deploy.image_registry",
                        "type": "host:port",
                        "description": "Optional registry override for CamMLSys images. Omit for the built-in default, 128.232.61.111:5000; older top-level image_registry and submit-service.image_registry keys are legacy fallbacks only.",
                    },
                    {
                        "path": "deploy.supernodes",
                        "type": "map[string]int",
                        "description": "Optional typed SuperNode counts such as {rpi4: 2, rpi5: 2}. If omitted, fedctl can fall back to the Flower project's local-simulation.num-supernodes unless a CLI flag or deploy preset overrides it.",
                    },
                    {
                        "path": "deploy.superexec.env",
                        "type": "map[string]string",
                        "description": "Environment variables injected into SuperExec server/client containers, commonly W&B or experiment-service settings.",
                    },
                ],
            },
            {
                "title": "deploy.placement",
                "description": "Nomad placement behavior and queue-gating defaults.",
                "fields": [
                    {
                        "path": "deploy.placement.allow_oversubscribe",
                        "type": "bool",
                        "description": "Allows multiple logical client workloads to share available compute capacity. false asks the submit service and renderer to use stricter placement.",
                    },
                    {
                        "path": "deploy.placement.spread_across_hosts",
                        "type": "bool",
                        "description": "Hard spread behavior for typed placements when oversubscription is disabled.",
                    },
                    {
                        "path": "deploy.placement.prefer_spread_across_hosts",
                        "type": "bool",
                        "description": "Soft spread behavior for oversubscribed typed runs; Nomad receives host affinities but placements remain flexible.",
                    },
                ],
            },
            {
                "title": "deploy.resources",
                "description": "CPU and memory reservations rendered into Nomad jobs and mirrored by submit-service capacity checks.",
                "fields": [
                    {
                        "path": "deploy.resources.supernode.default",
                        "type": "{cpu:int, mem:int}",
                        "description": "Default SuperNode CPU MHz and memory MB reservation.",
                    },
                    {
                        "path": "deploy.resources.supernode.<device>",
                        "type": "{cpu:int, mem:int}",
                        "description": "Optional per-device SuperNode reservation, for example rpi4 or rpi5.",
                    },
                    {
                        "path": "deploy.resources.superexec_clientapp",
                        "type": "{cpu:int, mem:int}",
                        "description": "CPU/memory reservation for each SuperExec clientapp task.",
                    },
                    {
                        "path": "deploy.resources.superexec_serverapp",
                        "type": "{cpu:int, mem:int}",
                        "description": "CPU/memory reservation for the SuperExec serverapp task.",
                    },
                    {
                        "path": "deploy.resources.superlink",
                        "type": "{cpu:int, mem:int}",
                        "description": "CPU/memory reservation for the SuperLink task.",
                    },
                ],
            },
            {
                "title": "deploy.network",
                "description": "Optional netem profile definitions and assignment defaults used when CLI --net is absent.",
                "fields": [
                    {
                        "path": "deploy.network.image",
                        "type": "image",
                        "description": "Optional container image override for the netem sidecar/wrapper. Omit for the built-in default, jiahborcn/netem:latest.",
                    },
                    {
                        "path": "deploy.network.default_profile",
                        "type": "string",
                        "description": "Default network profile label. It is also used as the deploy-config label in generated experiment names when present.",
                    },
                    {
                        "path": "deploy.network.default_assignment",
                        "type": "string | list[string]",
                        "description": "Fallback assignment used when --net is not passed, for example rpi5[*]=med or a list of assignment strings.",
                    },
                    {
                        "path": "deploy.network.interface",
                        "type": "string",
                        "description": "Network interface to shape, normally eth0 on the cluster.",
                    },
                    {
                        "path": "deploy.network.apply.superexec_serverapp",
                        "type": "bool",
                        "description": "Apply netem wrapping to the SuperExec serverapp path as well as the default SuperNode path.",
                    },
                    {
                        "path": "deploy.network.apply.superexec_clientapp",
                        "type": "bool",
                        "description": "Apply netem wrapping to SuperExec clientapp tasks as well as the default SuperNode path.",
                    },
                    {
                        "path": "deploy.network.profiles.<name>",
                        "type": "profile",
                        "description": "Bidirectional profile used by assignments. Supported profile keys include delay_ms, jitter_ms, loss_pct, rate_mbit, rate_latency_ms, and rate_burst_kbit.",
                    },
                    {
                        "path": "deploy.network.ingress_profiles.<name>",
                        "type": "profile",
                        "description": "Optional direction-specific profile for ingress traffic.",
                    },
                    {
                        "path": "deploy.network.egress_profiles.<name>",
                        "type": "profile",
                        "description": "Optional direction-specific profile for egress traffic.",
                    },
                ],
            },
            {
                "title": "legacy compatibility",
                "description": "Accepted for old files, but not the preferred spelling for new deploy configs.",
                "fields": [
                    {
                        "path": "image_registry",
                        "type": "host:port",
                        "description": "Legacy top-level registry fallback. Prefer deploy.image_registry.",
                    },
                    {
                        "path": "build.image_registry",
                        "type": "host:port",
                        "description": "Older build-specific registry fallback. Prefer deploy.image_registry.",
                    },
                    {
                        "path": "submit-service.image_registry",
                        "type": "host:port",
                        "description": "Legacy cluster-visible registry override. New configs should use a single deploy.image_registry value.",
                    },
                ],
            },
        ],
        "examples": [
            {
                "title": "Use the default CamMLSys deploy config",
                "body": "Most users can rely on the generated user deploy config after adding their bearer token.",
                "command": "FEDCTL_SUBMIT_TOKEN=<token> fedctl submit run ../quickstart-pytorch",
            },
            {
                "title": "Use an explicit project deploy config",
                "body": "Use this when the project has a checked-in or repo-local deployment preset.",
                "command": (
                    "fedctl submit run apps/fedctl_research \\\n"
                    "  --deploy-config .fedctl/main_compute_heterogeneity.yaml"
                ),
            },
        ],
        "notes": [
            "Resolution order is --deploy-config, project .fedctl/fedctl.yaml, then the active user profile.",
            "Fresh installs create a CamMLSys default deploy config; use fedctl submit register-token, add submit.token, or set FEDCTL_SUBMIT_TOKEN.",
            "deploy.image_registry is the canonical registry field for CamMLSys runs.",
            "deploy.supernodes is optional; when omitted, fedctl can fall back to the Flower project's local-simulation.num-supernodes.",
        ],
        "related_commands": [
            "submit register-token",
            "submit run",
            "submit status",
            "submit logs",
            "submit inventory",
        ],
    },
]
_HELP_COMMANDS = [
    {
        "name": "submit run",
        "summary": "Package a local Flower project, upload the archive, and create a queued submission.",
        "importance": "primary",
        "syntax": "fedctl submit run <project-dir> [OPTIONS]",
        "details": [
            "Use this command to turn a local Flower app or research project into a submit-service job. The runner inspects the project, builds or reuses the required images, uploads the project archive, creates the submission record, and dispatches work through Nomad.",
            "For dissertation experiments, the most repeatable form is to pass the project directory, an explicit run config, a deployment config via --deploy-config, a seeded submit image, and a seed.",
        ],
        "use_cases": [
            "Launch a quick local Flower project with the default deployment settings.",
            "Run a tracked experiment from a TOML config and fixed random seed.",
            "Keep Nomad jobs around after completion when you need live allocation logs for debugging.",
        ],
        "examples": [
            {
                "title": "Minimal project submission",
                "body": "Submit the project with default options and stream the runner output.",
                "command": "fedctl submit run ../quickstart-pytorch",
            },
            {
                "title": "Named run for easier tracking",
                "body": "Give the submission and W&B run a readable experiment name.",
                "command": "fedctl submit run ../quickstart-pytorch --exp pytorch-baseline-r1",
            },
            {
                "title": "Dissertation experiment with explicit config",
                "body": "Use the research app, a run config, a deployment config, a fixed seed, and the cluster submit image.",
                "command": (
                    "./.venv/bin/fedctl submit run apps/fedctl_research \\\n"
                    "  --run-config apps/fedctl_research/run_configs/network_heterogeneity/main/cifar10_cnn/iid/all_rpi5/fedbuff.toml \\\n"
                    "  --deploy-config apps/fedctl_research/repo_configs/network_heterogeneity/main/all_rpi5/none.yaml \\\n"
                    "  --submit-image 128.232.61.111:5000/fedctl-submit:latest \\\n"
                    "  --seed 1337"
                ),
            },
            {
                "title": "Debug failed deployment state",
                "body": "Keep Nomad jobs after completion or failure so their live allocation state can be inspected.",
                "command": "fedctl submit run ../quickstart-pytorch --exp debug-r1 --no-destroy --verbose",
            },
            {
                "title": "Override one run-config value",
                "body": "Patch a Flower run-config key without creating a new run-config TOML.",
                "command": "fedctl submit run apps/fedctl_research --run-config-override num-server-rounds=5 --seed 1337",
            },
        ],
        "flags": [
            {"name": "--run-config", "type": "PATH", "description": "Path to run config file"},
            {"name": "--run-config-override", "type": "TEXT", "description": "Override run config (repeatable)"},
            {"name": "--seed", "type": "INTEGER", "description": "Random seed for experiment"},
            {"name": "--flwr-version", "type": "TEXT", "description": "Flower version to use"},
            {"name": "--image", "type": "TEXT", "description": "Docker image for the submit job"},
            {"name": "--no-cache", "type": "FLAG", "description": "Don't use Docker build cache"},
            {"name": "--platform", "type": "TEXT", "description": "Docker build platform"},
            {"name": "--context", "type": "PATH", "description": "Docker build context directory"},
            {"name": "--push/--no-push", "type": "FLAG", "description": "Push Docker image to registry (default: yes)"},
            {"name": "--num-supernodes", "type": "INTEGER", "description": "Number of supernode tasks (default: 2)"},
            {"name": "--auto-supernodes/--no-auto-supernodes", "type": "FLAG", "description": "Auto-detect supernodes from project (default: yes)"},
            {"name": "--supernodes", "type": "TEXT", "description": "Supernode resource config (repeatable)"},
            {"name": "--net", "type": "TEXT", "description": "Network config (repeatable)"},
            {"name": "--allow-oversubscribe/--no-allow-oversubscribe", "type": "FLAG", "description": "Allow resource oversubscription"},
            {"name": "--deploy-config", "type": "PATH", "description": "Path to deploy config file"},
            {"name": "--exp", "type": "TEXT", "description": "Experiment name"},
            {"name": "--timeout", "type": "INTEGER", "description": "Timeout in seconds (default: 120)"},
            {"name": "--federation", "type": "TEXT", "description": "Federation config (default: remote-deployment)"},
            {"name": "--stream/--no-stream", "type": "FLAG", "description": "Stream job output (default: yes)"},
            {"name": "--verbose", "type": "FLAG", "description": "Show detailed output"},
            {"name": "--destroy/--no-destroy", "type": "FLAG", "description": "Cleanup Nomad jobs after completion (default: yes)"},
            {"name": "--submit-image", "type": "TEXT", "description": "Docker image for the submit task"},
            {"name": "--artifact-store", "type": "TEXT", "description": "Artifact storage URI"},
            {"name": "--priority", "type": "INTEGER", "description": "Job priority (higher = more priority)"},
        ],
        "notes": [
            "This is the main entrypoint for normal users.",
            "It handles inspect, archive, upload, and submit in one flow.",
            "Use --no-destroy when you want to inspect live Nomad jobs after completion.",
            "By default, output is streamed and Nomad jobs are destroyed after completion.",
        ],
        "related": ["submit ls", "submit status", "submit logs", "submit results"],
    },
    {
        "name": "submit register-token",
        "summary": "Register a user-scoped bearer token and save it in the user deploy config.",
        "importance": "standard",
        "syntax": "fedctl submit register-token --name <username>",
        "details": [
            "Use this command for first-time setup when the submit service has self-registration enabled. It calls the registration API without requiring an existing bearer token, receives a user-scoped token, and stores it locally.",
            "The token itself is not printed unless --print-token is passed.",
        ],
        "use_cases": [
            "Set up a fresh fedctl install without manually editing YAML.",
            "Create a replacement user token after an old one is revoked.",
            "Check that submit-service registration is enabled before running experiments.",
        ],
        "examples": [
            {
                "title": "Register a user token",
                "body": "The returned token is saved to the user deploy config.",
                "command": "fedctl submit register-token --name alice",
            },
            {
                "title": "Use an explicit deploy config for the endpoint",
                "body": "The endpoint can come from a deploy config while the token is saved to user config.",
                "command": "fedctl submit register-token --name alice --deploy-config .fedctl/fedctl.yaml",
            },
        ],
        "flags": [
            {"name": "--name", "type": "TEXT", "description": "Username attached to the registered token"},
            {"name": "--token", "type": "TEXT", "description": "Optional caller-provided bearer token; omit to let the service generate one"},
            {"name": "--deploy-config", "type": "PATH", "description": "Deploy config used to find submit.endpoint"},
            {"name": "--print-token", "type": "FLAG", "description": "Print the token after saving it locally"},
        ],
        "notes": [
            "Registration must be enabled on the submit service by the operator.",
            "Registered tokens are normal user tokens; they do not grant admin access.",
            "FEDCTL_SUBMIT_TOKEN still overrides the token saved in the deploy config.",
        ],
        "related": ["submit set-token", "submit run", "submit ls", "submit status"],
    },
    {
        "name": "submit set-token",
        "summary": "Save an existing submit-service bearer token in the user deploy config.",
        "importance": "standard",
        "syntax": "fedctl submit set-token [TOKEN]",
        "details": [
            "Use this command when you already have a bearer token, for example one generated by the web registration page. If TOKEN is omitted, fedctl prompts for it without echoing the input.",
            "The command validates the token against the submit service by default, then writes it to the user deploy config so future submit commands can authenticate without an exported environment variable.",
        ],
        "use_cases": [
            "Persist a token generated in the web UI.",
            "Move from a temporary FEDCTL_SUBMIT_TOKEN export to normal config-based authentication.",
            "Replace the token stored in ~/.config/fedctl/deploy-default.yaml.",
        ],
        "examples": [
            {
                "title": "Paste token into a hidden prompt",
                "body": "Recommended when copying a token from the web registration page.",
                "command": "fedctl submit set-token",
            },
            {
                "title": "Use an explicit endpoint config",
                "body": "Useful when the default profile does not point at the submit service yet.",
                "command": "fedctl submit set-token --deploy-config .fedctl/fedctl.yaml",
            },
            {
                "title": "Save without validation",
                "body": "Only use this when the submit service is temporarily unreachable.",
                "command": "fedctl submit set-token --no-validate",
            },
        ],
        "flags": [
            {"name": "TOKEN", "type": "TEXT", "description": "Bearer token to save; omit to use a hidden prompt"},
            {"name": "--deploy-config", "type": "PATH", "description": "Deploy config used to find submit.endpoint for validation"},
            {"name": "--no-validate", "type": "FLAG", "description": "Write the token without checking it against the submit service"},
        ],
        "notes": [
            "Tokens are saved in the user deploy config, not a project-local deploy config.",
            "FEDCTL_SUBMIT_TOKEN still overrides the saved token when the environment variable is set.",
        ],
        "related": ["submit register-token", "submit run", "submit ls"],
    },
    {
        "name": "submit ls",
        "summary": "List recent submissions from the submit service.",
        "importance": "standard",
        "syntax": "fedctl submit ls [--active|--completed|--failed|--cancelled|--all] [--limit N]",
        "details": [
            "Use this command as the queue overview. It is intentionally lightweight and is the quickest way to see which submissions are running, blocked, queued, or recently finished.",
            "The web UI shows the same underlying records, but this command is more convenient from a terminal during experiment batches.",
        ],
        "use_cases": [
            "Check whether the queue is blocked before submitting another batch.",
            "Find the submission ID needed for logs, status, cancellation, or results.",
            "Review terminal submissions after a long run sequence.",
        ],
        "examples": [
            {
                "title": "Show active submissions",
                "body": "List running, submitting, blocked, and queued work.",
                "command": "fedctl submit ls --active",
            },
            {
                "title": "Show recent completed submissions",
                "body": "Useful when collecting result artifact links after a batch.",
                "command": "fedctl submit ls --completed --limit 50",
            },
            {
                "title": "Audit everything visible to you",
                "body": "Include active and terminal records in one listing.",
                "command": "fedctl submit ls --all --limit 100",
            },
        ],
        "notes": [
            "Default output shows the active queue even when no status flag is provided.",
            "Use --all when you are not sure whether a submission is still active or already terminal.",
        ],
        "related": ["submit status", "submit logs", "submit cancel", "submit results"],
    },
    {
        "name": "submit status",
        "summary": "Show the current status, blocked reason, or failure message for one submission.",
        "importance": "standard",
        "syntax": "fedctl submit status <submission-id>",
        "details": [
            "Status is the first diagnostic command for a single submission. It tells you whether the submit service thinks the job is queued, blocked, submitting, running, completed, failed, or cancelled.",
            "When a submission is blocked, the status output should explain the queue-gating reason, such as strict placement waiting for another running submission or insufficient typed compute nodes.",
        ],
        "use_cases": [
            "Check whether a submission is blocked by resource gating or actually running.",
            "Confirm that a cancelled or failed submission reached a terminal state.",
            "Get the failure message before switching to logs for deeper inspection.",
        ],
        "examples": [
            {
                "title": "Inspect one submission",
                "body": "Use the ID from submit ls or the web UI.",
                "command": "fedctl submit status sub-20260227182713-5413",
            },
            {
                "title": "Typical blocked-run workflow",
                "body": "List active submissions, then inspect the blocked record.",
                "command": "fedctl submit ls --active\nfedctl submit status sub-20260227182713-5413",
            },
        ],
        "notes": [
            "Use this first when a run looks stuck or blocked.",
            "If status says running but no progress appears, inspect submit logs first, then downstream Flower logs.",
        ],
        "related": ["submit ls", "submit logs", "submit cancel", "submit inventory"],
    },
    {
        "name": "submit logs",
        "summary": "Read live or archived logs for the submit job and downstream Flower jobs.",
        "importance": "standard",
        "syntax": "fedctl submit logs <submission-id> [OPTIONS]",
        "details": [
            "Logs are server-mediated: the CLI asks the submit service for the requested stream. The service first checks live Nomad allocations and then falls back to archived logs when they are available.",
            "Start with the submit job logs for packaging, build, upload, and deployment failures. If deployment succeeded, switch to superlink, supernodes, or superexec logs to inspect the Flower runtime.",
        ],
        "use_cases": [
            "Debug project packaging, Docker build, registry push, or Nomad deployment failures.",
            "Follow the submit runner while a job is starting.",
            "Inspect one supernode or clientapp stream by index after Flower has started.",
            "Read archived logs after cleanup has destroyed the live Nomad allocations.",
        ],
        "examples": [
            {
                "title": "Read submit-runner output",
                "body": "This is the first place to look for inspect, build, upload, and deploy errors.",
                "command": "fedctl submit logs sub-20260227182713-5413",
            },
            {
                "title": "Follow a live submit job",
                "body": "Stream output while the runner is still active.",
                "command": "fedctl submit logs sub-20260227182713-5413 --follow",
            },
            {
                "title": "Inspect SuperLink errors",
                "body": "Use stderr when the Flower server/link layer crashes or rejects connections.",
                "command": "fedctl submit logs sub-20260227182713-5413 --job superlink --stderr",
            },
            {
                "title": "Inspect a specific supernode",
                "body": "Grouped jobs use one-based indices.",
                "command": "fedctl submit logs sub-20260227182713-5413 --job supernodes --index 2",
            },
            {
                "title": "Inspect a specific clientapp",
                "body": "Use clientapp logs for task/model/data errors raised inside the research app.",
                "command": "fedctl submit logs sub-20260227182713-5413 --job superexec_clientapps --index 2 --stdout",
            },
        ],
        "flags": [
            {"name": "--job", "type": "TEXT", "description": "Job to read logs from (submit, superlink, supernodes, superexec_serverapp, superexec_clientapps)"},
            {"name": "--task", "type": "TEXT", "description": "Nomad task name within the job"},
            {"name": "--index", "type": "INTEGER", "description": "Job/task index for grouped jobs (default: 1)"},
            {"name": "--stderr/--stdout", "type": "FLAG", "description": "Show stderr or stdout"},
            {"name": "--follow", "type": "FLAG", "description": "Stream logs continuously"},
        ],
        "notes": [
            "Use --job supernodes with either --task or --index to target one supernode task.",
            "When Nomad allocations are gone, the service falls back to archived logs if available.",
            "--index is one-based, so --index 1 selects the first grouped task.",
        ],
        "related": ["submit status", "submit results", "submit inventory"],
    },
    {
        "name": "submit cancel",
        "summary": "Stop an active submission and mark it cancelled.",
        "importance": "standard",
        "syntax": "fedctl submit cancel <submission-id>",
        "details": [
            "Cancellation is the safe way to stop work that is queued, blocked, submitting, or running. The submit service marks the submission as cancelled and asks Nomad to stop related jobs when applicable.",
            "Use cancellation instead of deleting records directly; it preserves enough history to understand what was stopped.",
        ],
        "use_cases": [
            "Stop a run submitted with the wrong experiment or deployment config.",
            "Clear a blocked queue entry so the next submission can proceed.",
            "Abort a running job before purging Nomad jobs manually.",
        ],
        "examples": [
            {
                "title": "Cancel one submission",
                "body": "Use the exact submission ID from submit ls or the web UI.",
                "command": "fedctl submit cancel sub-20260227182713-5413",
            },
            {
                "title": "Check active queue before cancelling",
                "body": "Confirm the target ID and status first.",
                "command": "fedctl submit ls --active\nfedctl submit status sub-20260227182713-5413\nfedctl submit cancel sub-20260227182713-5413",
            },
        ],
        "notes": [
            "Use this for queued, running, or blocked submissions.",
            "After cancellation, use submit status or the web UI to confirm the record is terminal.",
        ],
        "related": ["submit ls", "submit status", "submit purge"],
    },
    {
        "name": "submit purge",
        "summary": "Delete submission history, either for one terminal submission or for all history.",
        "importance": "standard",
        "syntax": "fedctl submit purge [submission-id]",
        "details": [
            "Purge is for cleanup of submission-service records, not for stopping active work. Cancel active work first, then purge once the submission is terminal.",
            "Purging without an ID is intentionally broad: it clears submission history visible to the caller according to service permissions. Use the single-ID form when you only want to remove one completed, failed, or cancelled record.",
        ],
        "use_cases": [
            "Remove old terminal records from the UI after collecting results.",
            "Clear a cancelled or failed test submission.",
            "Reset the submit-service history during operator maintenance.",
        ],
        "examples": [
            {
                "title": "Purge one terminal submission",
                "body": "This removes the submit-service record for one completed, failed, or cancelled run.",
                "command": "fedctl submit purge sub-20260227182713-5413",
            },
            {
                "title": "Purge all visible history",
                "body": "Use this only for deliberate cleanup after confirming no active records are needed.",
                "command": "fedctl submit purge",
            },
            {
                "title": "Safe cleanup sequence",
                "body": "Cancel first if the run is still active, then purge after it becomes terminal.",
                "command": "fedctl submit cancel sub-20260227182713-5413\nfedctl submit status sub-20260227182713-5413\nfedctl submit purge sub-20260227182713-5413",
            },
        ],
        "notes": [
            "Purging a single submission is allowed for the owner or admin, but only after it is completed, failed, or cancelled.",
            "Purging without an ID clears the whole submission history and is the stronger action.",
            "Purge does not replace Nomad operational cleanup for live jobs.",
        ],
        "related": ["submit cancel", "submit ls", "submit status"],
    },
    {
        "name": "submit results",
        "summary": "Show or download result artifact URLs recorded for a submission.",
        "importance": "standard",
        "syntax": "fedctl submit results <submission-id> [--download] [--out PATH]",
        "details": [
            "Use results after a submission has completed and uploaded artifacts. Without --download, the command reports result locations; with --download, it writes artifacts into a local directory.",
            "Result availability depends on the submit runner and research app producing artifacts. If no artifacts are listed, inspect submit logs to check whether upload occurred.",
        ],
        "use_cases": [
            "Copy artifact URLs for a completed experiment.",
            "Download result bundles into a local analysis directory.",
            "Check whether a completed submission uploaded expected outputs.",
        ],
        "examples": [
            {
                "title": "Show recorded artifact locations",
                "body": "Use this first to confirm that the submission produced results.",
                "command": "fedctl submit results sub-20260227182713-5413",
            },
            {
                "title": "Download artifacts locally",
                "body": "Write all downloadable result artifacts under ./results.",
                "command": "fedctl submit results sub-20260227182713-5413 --download --out ./results",
            },
            {
                "title": "Check completion before downloading",
                "body": "Avoid downloading before artifact upload has finished.",
                "command": "fedctl submit status sub-20260227182713-5413\nfedctl submit results sub-20260227182713-5413 --download --out ./results",
            },
        ],
        "notes": [
            "This is useful when the runner uploaded result files and you want the URLs or local copies.",
            "For failed submissions, logs are usually more useful than results unless partial artifacts were uploaded.",
        ],
        "related": ["submit status", "submit logs", "submit ls"],
    },
    {
        "name": "submit inventory",
        "summary": "Inspect the Nomad node inventory exposed by the submit service.",
        "importance": "standard",
        "syntax": "fedctl submit inventory [--status STATUS] [--class CLASS] [--device-type TYPE] [--detail] [--json]",
        "details": [
            "Inventory exposes the submit service's view of Nomad node readiness and allocation pressure. It is useful for understanding why a placement is blocked before submitting or while a submission waits.",
            "Use --detail for human-readable allocation pressure and --json when feeding the data into scripts.",
        ],
        "use_cases": [
            "Check how many ready compute nodes are available.",
            "Verify whether rpi4 or rpi5 nodes are saturated before submitting typed workloads.",
            "Inspect submit/link nodes separately from compute workers.",
            "Export node state as JSON for a capacity debugging script.",
        ],
        "examples": [
            {
                "title": "Show all visible inventory",
                "body": "Get the current cluster overview from the submit service.",
                "command": "fedctl submit inventory",
            },
            {
                "title": "Filter ready submit nodes",
                "body": "Useful when debugging whether the submit runner can be placed.",
                "command": "fedctl submit inventory --status ready --class submit",
            },
            {
                "title": "Inspect ready RPi5 compute nodes",
                "body": "Use this before all-RPi5 or device-typed runs.",
                "command": "fedctl submit inventory --status ready --class compute --device-type rpi5 --detail",
            },
            {
                "title": "Export inventory as JSON",
                "body": "Use JSON output for scripts or precise resource inspection.",
                "command": "fedctl submit inventory --detail --json",
            },
        ],
        "notes": [
            "This is mainly an operator/admin command for checking cluster capacity and placement constraints.",
            "If a strict submission is blocked, inventory helps explain whether the issue is node count, device type, CPU, or memory pressure.",
        ],
        "related": ["submit ls", "submit status", "submit run"],
    },
]
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_ANSI_CONVERTER = Ansi2HTMLConverter(inline=True, dark_bg=False)


@router.get("/", response_class=HTMLResponse, response_model=None)
def home(request: Request) -> RedirectResponse:
    if current_ui_principal(request) is None:
        return RedirectResponse(url="/login", status_code=303)
    return RedirectResponse(url="/submissions", status_code=303)


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    if current_ui_principal(request) is not None:
        return RedirectResponse(url="/submissions", status_code=303)
    return _render(
        request,
        "login.html",
        {"error": None, "registration_enabled": request.app.state.cfg.registration_enabled},
    )


@router.post("/login", response_class=HTMLResponse, response_model=None)
def login_submit(request: Request, token: str = Form(...)) -> HTMLResponse | RedirectResponse:
    cfg: SubmitConfig = request.app.state.cfg
    try:
        login_via_token(request, cfg, token)
    except HTTPException as exc:
        return _render(
            request,
            "login.html",
            {
                "error": exc.detail if isinstance(exc.detail, str) else "Login failed.",
                "registration_enabled": request.app.state.cfg.registration_enabled,
            },
            status_code=exc.status_code,
        )
    return RedirectResponse(url="/submissions", status_code=303)


@router.get("/register", response_class=HTMLResponse, response_model=None)
def register_page(request: Request) -> HTMLResponse | RedirectResponse:
    cfg: SubmitConfig = request.app.state.cfg
    if not cfg.registration_enabled:
        return RedirectResponse(url="/login", status_code=303)
    return _render(request, "register.html", {"error": None, "registered": None})


@router.post("/register", response_class=HTMLResponse, response_model=None)
def register_submit(
    request: Request,
    name: str = Form(...),
    token: str | None = Form(None),
) -> HTMLResponse:
    cfg: SubmitConfig = request.app.state.cfg
    try:
        registered = register_bearer_token(
            request.app.state.storage,
            cfg,
            name=name,
            token=token,
        )
    except HTTPException as exc:
        return _render(
            request,
            "register.html",
            {
                "error": exc.detail if isinstance(exc.detail, str) else "Registration failed.",
                "registered": None,
            },
            status_code=exc.status_code,
        )
    return _render(request, "register.html", {"error": None, "registered": registered})


@router.post("/logout", response_model=None)
def logout_submit(request: Request) -> RedirectResponse:
    logout(request)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/submissions", response_class=HTMLResponse, response_model=None)
def submissions_page(
    request: Request,
    status: str = Query("active"),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(_SUBMISSIONS_UI_DEFAULT_LIMIT, ge=1, le=_SUBMISSIONS_UI_MAX_LIMIT),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/login", status_code=303)
    status_filter = status if status in _STATUS_FILTERS else "active"
    search_query = (q or "").strip()
    auth_principal = principal.as_auth_principal()
    total_rows = count_visible_submissions_for_ui(
        request.app.state.storage,
        auth_principal,
        status_filter=status_filter,
        search_query=search_query,
    )
    page_count = max(1, (total_rows + limit - 1) // limit)
    current_page = min(page, page_count)
    offset = (current_page - 1) * limit
    rows = list_visible_submissions_for_ui(
        request.app.state.storage,
        auth_principal,
        status_filter=status_filter,
        limit=limit,
        offset=offset,
        search_query=search_query,
        default_priority=request.app.state.cfg.default_priority,
    )
    row_views = [_submission_row_view(row, principal.as_auth_principal()) for row in rows]
    queue_rows = _queue_panel_rows(row_views, default_priority=request.app.state.cfg.default_priority)
    pagination = _pagination_context(
        status_filter=status_filter,
        q=search_query,
        page=current_page,
        limit=limit,
        total_rows=total_rows,
        page_count=page_count,
    )
    return _render(
        request,
        "submissions_list.html",
        {
            "status_filter": status_filter,
            "status_filters": _STATUS_FILTERS,
            "search_query": search_query,
            "stats": submission_stats_for_principal(request.app.state.storage, auth_principal),
            "rows": row_views,
            "queue_running_rows": queue_rows["running"],
            "queue_pending_rows": queue_rows["pending"],
            "quick_command": _submission_list_command(status_filter),
            "return_to": _submission_list_return_to(
                status_filter=status_filter,
                q=search_query,
                page=current_page,
                limit=limit,
            ),
            "pagination": pagination,
            "limit": limit,
        },
    )


@router.get("/help", response_class=HTMLResponse, response_model=None)
def help_page(request: Request) -> HTMLResponse:
    return _render(
        request,
        "help.html",
        {
            "commands": _HELP_COMMANDS,
            "config_sections": _HELP_CONFIG_SECTIONS,
            "quickstart_steps": [
                {
                    "title": "Install fedctl",
                    "body": "Install the CLI in the Python environment you use for Flower projects.",
                    "command": "python -m pip install fedctl",
                },
                {
                    "title": "Register a bearer token",
                    "body": (
                        "The first fedctl command creates ~/.config/fedctl/config.toml and "
                        "~/.config/fedctl/deploy-default.yaml. Register a user-scoped bearer token from the CLI; "
                        "the command saves the returned token locally. "
                        "FEDCTL_SUBMIT_TOKEN remains available for temporary overrides."
                    ),
                    "command": (
                        "fedctl submit register-token --name <username>\n"
                        "fedctl submit ls"
                    ),
                },
                {
                    "title": "Submit a Flower project",
                    "body": (
                        "For a normal Flower project, you can submit the project directory directly. "
                        "fedctl uses the generated CamMLSys deploy defaults unless the project provides its own config."
                    ),
                    "command": "fedctl submit run <project-dir>",
                },
                {
                    "title": "Add config files when needed",
                    "body": (
                        "Use a run config for Flower run settings and a deploy config for cluster execution settings. "
                        "Open the config file cards below for the full field reference."
                    ),
                    "command": (
                        "fedctl submit run <project-dir> \\\n"
                        "  --run-config path/to/run.toml \\\n"
                        "  --deploy-config path/to/deploy.yaml"
                    ),
                },
                {
                    "title": "Check queue and status",
                    "body": "List active submissions, then inspect one specific submission if needed.",
                    "command": "fedctl submit ls --active\nfedctl submit status <submission-id>",
                },
                {
                    "title": "Inspect logs and download results",
                    "body": "Follow logs while the run starts, then download result artifacts after completion.",
                    "command": (
                        "fedctl submit logs <submission-id> --job submit --follow\n"
                        "fedctl submit results <submission-id> --download --out ./results"
                    ),
                },
            ],
        },
    )


@router.get("/help/config/{config_slug}", response_class=HTMLResponse, response_model=None)
def help_config_detail(config_slug: str, request: Request) -> HTMLResponse | RedirectResponse:
    config = None
    for item in _HELP_CONFIG_SECTIONS:
        if item["slug"] == config_slug:
            config = item
            break

    if config is None:
        return RedirectResponse(url="/help", status_code=303)

    return _render(
        request,
        "help_config_detail.html",
        {
            "config": config,
            "all_configs": _HELP_CONFIG_SECTIONS,
        },
    )


@router.get("/help/{command_slug}", response_class=HTMLResponse, response_model=None)
def help_command_detail(command_slug: str, request: Request) -> HTMLResponse | RedirectResponse:
    # Find command by slug (convert name to slug format)
    command = None
    for cmd in _HELP_COMMANDS:
        cmd_slug = cmd["name"].lower().replace(" ", "-")
        if cmd_slug == command_slug:
            command = cmd
            break

    if command is None:
        return RedirectResponse(url="/help", status_code=303)

    return _render(
        request,
        "help_command_detail.html",
        {
            "command": command,
            "all_commands": _HELP_COMMANDS,
        },
    )


@router.get("/submissions/{submission_id}", response_class=HTMLResponse, response_model=None)
def submission_detail_page(
    submission_id: str,
    request: Request,
    return_to: str | None = Query(None),
    job: str = Query("submit"),
    task: str | None = Query(None),
    index: int = Query(1, ge=1),
    stderr: bool = Query(False),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/login", status_code=303)
    record = get_submission_or_404(
        request.app.state.storage,
        submission_id,
        principal.as_auth_principal(),
    )
    logs_content, logs_error, logs_source = _resolve_logs_for_view(
        request,
        record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
    )
    return _render_submission_detail(
        request,
        principal.role,
        record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
        logs_content=logs_content,
        logs_error=logs_error,
        logs_source=logs_source,
        return_to=_safe_return_to(return_to),
    )


@router.post("/submissions/{submission_id}/cancel", response_model=None)
def submission_cancel(
    submission_id: str,
    request: Request,
) -> RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/login", status_code=303)
    cancel_submission_record(
        request.app.state.storage,
        request.app.state.cfg,
        submission_id=submission_id,
        principal=principal.as_auth_principal(),
    )
    return RedirectResponse(
        url=_append_notice(f"/submissions/{submission_id}", "Submission cancelled."),
        status_code=303,
    )


@router.post("/submissions/{submission_id}/purge", response_model=None)
def submission_purge(
    submission_id: str,
    request: Request,
    return_to: str | None = Form(None),
) -> RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/login", status_code=303)
    purge_submission_record(
        request.app.state.storage,
        submission_id=submission_id,
        principal=principal.as_auth_principal(),
    )
    return RedirectResponse(
        url=_append_notice(_safe_return_to(return_to), "Submission purged."),
        status_code=303,
    )


@router.get("/submissions/{submission_id}/logs", response_class=HTMLResponse, response_model=None)
def submission_logs_panel(
    submission_id: str,
    request: Request,
    job: str = Query("submit"),
    task: str | None = Query(None),
    index: int = Query(1, ge=1),
    stderr: bool = Query(False),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/login", status_code=303)
    record = get_submission_or_404(
        request.app.state.storage,
        submission_id,
        principal.as_auth_principal(),
    )
    logs_content, logs_error, logs_source = _resolve_logs_for_view(
        request,
        record,
        job=job,
        task=task,
        index=index,
        stderr=stderr,
    )
    return templates.TemplateResponse(
        request=request,
        name="logs_panel.html",
        context={
            "request": request,
            "submission": _submission_detail_view(record, principal.role),
            "logs_content": logs_content,
            "logs_html": _render_logs_html(logs_content),
            "logs_error": logs_error,
            "logs_source": logs_source,
            "job": job,
            "task": task or "",
            "index": index,
            "stderr": stderr,
            "log_jobs": _LOG_JOBS,
        },
    )


@router.get("/nodes", response_class=HTMLResponse, response_model=None)
def nodes_page(
    request: Request,
    q: str | None = Query(None),
) -> HTMLResponse | RedirectResponse:
    principal = current_ui_principal(request)
    if principal is None:
        return RedirectResponse(url="/login", status_code=303)
    inventory = request.app.state.inventory
    is_admin = principal.role == "admin"
    search_query = (q or "").strip()
    try:
        nodes = inventory.list_nodes(include_allocs=True)
    except Exception as exc:
        return _render(
            request,
            "nodes.html",
            {
                "nodes": [],
                "class_groups": [],
                "class_summaries": [],
                "filters": {"q": search_query},
                "error": str(exc),
                "quick_command": _inventory_command(),
                "show_private": is_admin,
            },
            status_code=502,
        )
    filtered = []
    for node in nodes:
        view = _node_view(node, include_private=is_admin)
        if search_query and not _node_matches_query(view, search_query):
            continue
        filtered.append(view)
    filtered.sort(key=_node_sort_key)
    class_groups = _group_nodes_by_class(filtered)
    class_summaries = _summarize_nodes_by_class(filtered)
    return _render(
        request,
        "nodes.html",
        {
            "nodes": filtered,
            "class_groups": class_groups,
            "class_summaries": class_summaries,
            "filters": {"q": search_query},
            "error": None,
            "quick_command": _inventory_command(),
            "show_private": is_admin,
        },
    )


@router.api_route("/ui", methods=["GET", "POST"], response_model=None)
@router.api_route("/ui/{legacy_path:path}", methods=["GET", "POST"], response_model=None)
def legacy_ui_redirect(request: Request, legacy_path: str = "") -> RedirectResponse:
    target = _legacy_ui_path_to_clean(str(request.url.path))
    if request.url.query:
        target = f"{target}?{request.url.query}"
    status_code = 303 if request.method == "GET" else 307
    return RedirectResponse(url=target, status_code=status_code)



def _render_submission_detail(
    request: Request,
    role: str,
    record: dict[str, Any],
    *,
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
    logs_content: str | None,
    logs_error: str | None,
    logs_source: str | None,
    return_to: str,
) -> HTMLResponse:
    detail = _submission_detail_view(record, role)
    return _render(
        request,
        "submission_detail.html",
        {
            "submission": detail,
            "logs_content": logs_content,
            "logs_html": _render_logs_html(logs_content),
            "logs_error": logs_error,
            "logs_source": logs_source,
            "job": job,
            "task": task or "",
            "index": index,
            "stderr": stderr,
            "log_jobs": _LOG_JOBS,
            "return_to": return_to,
        },
    )



def _resolve_logs_for_view(
    request: Request,
    record: dict[str, Any],
    *,
    job: str,
    task: str | None,
    index: int,
    stderr: bool,
) -> tuple[str | None, str | None, str | None]:
    try:
        resolved = resolve_submission_logs_detail(
            record,
            request.app.state.cfg,
            job=job,
            task=task,
            index=index,
            stderr=stderr,
            follow=False,
        )
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else "Failed to load logs."
        return None, detail, None
    return resolved.content, None, resolved.source



def _render(
    request: Request,
    template: str,
    context: dict[str, Any],
    *,
    status_code: int = 200,
) -> HTMLResponse:
    principal = current_ui_principal(request)
    merged = {
        "request": request,
        "principal": principal,
        **context,
    }
    return templates.TemplateResponse(
        request=request,
        name=template,
        context=merged,
        status_code=status_code,
    )


def _safe_return_to(value: str | None) -> str:
    if isinstance(value, str):
        if value.startswith("/submissions"):
            return value
        if value.startswith("/ui/submissions"):
            return _legacy_ui_path_to_clean(value)
    return "/submissions"


def _legacy_ui_path_to_clean(value: str) -> str:
    parts = urlsplit(value)
    path = parts.path
    if path == "/ui":
        clean_path = "/"
    elif path.startswith("/ui/"):
        clean_path = path[3:] or "/"
    else:
        clean_path = path
    return urlunsplit((parts.scheme, parts.netloc, clean_path, parts.query, parts.fragment))


def _append_notice(url: str, message: str, kind: str = "success") -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["notice"] = message
    query["notice_kind"] = kind
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _submission_list_return_to(
    *,
    status_filter: str,
    q: str,
    page: int = 1,
    limit: int = _SUBMISSIONS_UI_DEFAULT_LIMIT,
) -> str:
    params = {"status": status_filter}
    if q:
        params["q"] = q
    if page > 1:
        params["page"] = str(page)
    if limit != _SUBMISSIONS_UI_DEFAULT_LIMIT:
        params["limit"] = str(limit)
    return urlunsplit(("", "", "/submissions", urlencode(params), ""))


def _pagination_context(
    *,
    status_filter: str,
    q: str,
    page: int,
    limit: int,
    total_rows: int,
    page_count: int,
) -> dict[str, Any]:
    def url_for(page_value: int) -> str:
        return _submission_list_return_to(
            status_filter=status_filter,
            q=q,
            page=page_value,
            limit=limit,
        )

    if total_rows <= 0:
        start = 0
        end = 0
    else:
        start = (page - 1) * limit + 1
        end = min(total_rows, page * limit)
    return {
        "page": page,
        "limit": limit,
        "total": total_rows,
        "page_count": page_count,
        "start": start,
        "end": end,
        "has_previous": page > 1,
        "has_next": page < page_count,
        "previous_url": url_for(page - 1) if page > 1 else None,
        "next_url": url_for(page + 1) if page < page_count else None,
    }


def _contains_query(values: list[object], query: str) -> bool:
    needle = query.casefold()
    return any(needle in str(value or "").casefold() for value in values)


def _submission_matches_query(record: dict[str, Any], query: str) -> bool:
    return _contains_query(
        [
            record.get("id"),
            record.get("project_name"),
            record.get("experiment"),
            record.get("user"),
            record.get("namespace"),
        ],
        query,
    )


def _node_matches_query(record: dict[str, Any], query: str) -> bool:
    return _contains_query(
        [
            record.get("name"),
            record.get("id"),
            record.get("status"),
            record.get("node_class"),
            record.get("device_type"),
            record.get("alloc_count"),
            record.get("alloc_summary"),
        ],
        query,
    )



def _submission_row_view(record: dict[str, Any], principal: Any) -> dict[str, Any]:
    status = str(record.get("status") or "unknown")
    owner = record.get("user")
    is_admin = getattr(principal, "role", "") == "admin"
    is_owner = isinstance(owner, str) and owner == getattr(principal, "name", None)
    can_view_detail = is_admin or is_owner
    project_name = record.get("project_name") or "-"
    experiment = record.get("experiment") or "-"
    blocked_reason = record.get("blocked_reason") or record.get("error_message") or ""
    if not can_view_detail:
        project_name = "Private"
        experiment = "Private submission"
        blocked_reason = ""
    return {
        "id": record.get("id"),
        "project_name": project_name,
        "experiment": experiment,
        "status": status,
        "owner": owner if (is_admin or not is_owner) else None,
        "is_owner": is_owner,
        "can_view_detail": can_view_detail,
        "created_at": _fmt_dt(record.get("created_at")),
        "started_at": _fmt_dt(record.get("started_at")),
        "finished_at": _fmt_dt(record.get("finished_at")),
        "queue_wait": _fmt_queue_wait(record.get("created_at"), record.get("started_at"), status),
        "runtime": _fmt_runtime(record.get("started_at"), record.get("finished_at"), status),
        "blocked_reason": blocked_reason,
        "namespace": record.get("namespace") or "-",
        "priority": record.get("priority"),
    }


def _queue_panel_rows(
    rows: list[dict[str, Any]],
    *,
    default_priority: int,
) -> dict[str, list[dict[str, Any]]]:
    running = [row for row in rows if row.get("status") == "running"]
    pending = [row for row in rows if row.get("status") in {"queued", "blocked"}]

    def pending_key(row: dict[str, Any]) -> tuple[int, str, str]:
        priority = row.get("priority")
        if priority is None:
            priority = default_priority
        created_at = row.get("created_at")
        created_iso = ""
        if isinstance(created_at, dict):
            created_iso = str(created_at.get("iso") or "")
        return (-int(priority), created_iso, str(row.get("id") or ""))

    return {"running": running, "pending": sorted(pending, key=pending_key)}



def _submission_detail_view(record: dict[str, Any], role: str) -> dict[str, Any]:
    jobs = record.get("jobs") if isinstance(record.get("jobs"), dict) else {}
    result_artifacts = record.get("result_artifacts")
    if not isinstance(result_artifacts, list):
        result_artifacts = []
    args = record.get("args") if isinstance(record.get("args"), list) else []
    submit_request = (
        record.get("submit_request") if isinstance(record.get("submit_request"), dict) else {}
    )
    return {
        "id": record.get("id"),
        "project_name": record.get("project_name") or "-",
        "experiment": record.get("experiment") or "-",
        "status": record.get("status") or "unknown",
        "owner": record.get("user") if role == "admin" else record.get("user"),
        "namespace": record.get("namespace") or "-",
        "priority": record.get("priority") if record.get("priority") is not None else "-",
        "created_at": _fmt_dt(record.get("created_at")),
        "started_at": _fmt_dt(record.get("started_at")),
        "finished_at": _fmt_dt(record.get("finished_at")),
        "queue_wait": _fmt_queue_wait(record.get("created_at"), record.get("started_at"), record.get("status")),
        "runtime": _fmt_runtime(record.get("started_at"), record.get("finished_at"), record.get("status")),
        "nomad_job_id": record.get("nomad_job_id") or "-",
        "artifact_url": _link_entry_view(record.get("artifact_url")),
        "submit_image": record.get("submit_image") or "-",
        "submit_request": submit_request,
        "submit_request_view": _submit_request_view(submit_request),
        "args": args,
        "args_view": [_arg_view(arg, idx) for idx, arg in enumerate(args, start=1)],
        "jobs": jobs,
        "job_entries": _job_entries_view(jobs),
        "result_location": _link_entry_view(record.get("result_location")),
        "result_artifacts": _artifact_rows_view(result_artifacts),
        "error_message": record.get("error_message") or "",
        "blocked_reason": record.get("blocked_reason") or "",
        "can_cancel": is_cancellable(record.get("status")),
        "can_purge": is_purgeable(record.get("status")),
    }


def _submit_request_view(submit_request: dict[str, Any]) -> dict[str, Any]:
    command_preview = submit_request.get("command_preview")
    options = submit_request.get("options") if isinstance(submit_request.get("options"), dict) else {}
    summary_order = [
        "experiment",
        "num_supernodes",
        "priority",
        "federation",
        "image",
        "submit_image",
    ]
    detail_order = [
        "artifact_store",
        "timeout",
        "stream",
        "destroy",
        "auto_supernodes",
        "allow_oversubscribe",
        "push",
        "platform",
        "context",
        "deploy_config",
        "repo_config",
        "verbose",
        "supernodes",
        "net",
    ]
    summary_items = _request_items(options, summary_order)
    detail_items = _request_items(options, detail_order)
    return {
        "path_input": submit_request.get("path_input") or "",
        "project_root": submit_request.get("project_root") or "",
        "cwd": submit_request.get("cwd") or "",
        "command_preview": command_preview if isinstance(command_preview, str) else "",
        "summary_items": summary_items,
        "detail_items": detail_items,
    }


def _request_items(options: dict[str, Any], order: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for key in order:
        if key not in options:
            continue
        items.append(
            {
                "label": key.replace("_", " "),
                "value": _request_value(options[key]),
            }
        )
    return items


def _request_value(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _link_entry_view(value: Any) -> dict[str, str] | None:
    if not isinstance(value, str) or not value or value == "-":
        return None
    label = _artifact_name_from_url(value) or value
    return {
        "url": value,
        "label": label,
        "type": _artifact_type(label),
        "signed": "yes" if _is_presigned_url(value) else "no",
    }


def _artifact_rows_view(artifacts: list[Any]) -> dict[str, list[dict[str, str]]]:
    rows = [_artifact_view(item, idx) for idx, item in enumerate(artifacts, start=1)]
    primary = [row for row in rows if row["priority"] == "primary"]
    secondary = [row for row in rows if row["priority"] != "primary"]
    return {"primary": primary, "secondary": secondary}


def _artifact_view(item: Any, index: int) -> dict[str, str]:
    if isinstance(item, dict):
        url = str(item.get("url") or item.get("href") or item.get("path") or item.get("name") or "-")
        label = str(item.get("name") or item.get("filename") or _artifact_name_from_url(url) or f"artifact-{index}")
    else:
        url = str(item)
        label = _artifact_name_from_url(url) or f"artifact-{index}"
    artifact_type = _artifact_type(label)
    return {
        "label": label,
        "url": url,
        "type": artifact_type,
        "signed": "yes" if _is_presigned_url(url) else "no",
        "priority": "primary" if _is_primary_artifact(label) else "secondary",
    }


def _artifact_name_from_url(url: str) -> str:
    trimmed = url.split("?", 1)[0].rstrip("/")
    if not trimmed:
        return ""
    name = trimmed.rsplit("/", 1)[-1]
    return name or trimmed


def _artifact_type(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".json",)):
        return "json"
    if lower.endswith((".csv", ".tsv", ".parquet")):
        return "table"
    if lower.endswith((".zip", ".tar", ".tar.gz", ".tgz")):
        return "archive"
    if lower.endswith((".png", ".jpg", ".jpeg", ".svg", ".pdf")):
        return "report"
    if lower.endswith((".pt", ".pth", ".bin", ".onnx", ".ckpt", ".npz", ".npy")):
        return "model"
    if lower.endswith((".log", ".txt")):
        return "log"
    return "artifact"


def _is_primary_artifact(name: str) -> bool:
    lower = name.lower()
    primary_markers = (
        "result",
        "summary",
        "metric",
        "report",
        "model",
        "final",
        "output",
    )
    return any(marker in lower for marker in primary_markers)


def _is_presigned_url(url: str) -> bool:
    lower = url.lower()
    return "x-amz-signature=" in lower or "x-amz-algorithm=" in lower


def _node_sort_key(node: dict[str, Any]) -> tuple[int, str, str]:
    class_order = {"link": 0, "submit": 1, "node": 2}
    node_class = str(node.get("node_class") or "").strip().lower()
    name = str(node.get("name") or "").strip().lower()
    node_id = str(node.get("id") or "").strip().lower()
    return (class_order.get(node_class, 99), name, node_id)


def _node_status_bucket(node: dict[str, Any]) -> str:
    status = str(node.get("status") or "").strip().lower()
    alloc_count = int(node.get("alloc_count") or 0)
    if status not in {"ready", "up"}:
        return "down"
    if alloc_count > 0:
        return "busy"
    return "ready"


def _group_nodes_by_class(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {"link": "Link nodes", "submit": "Submit nodes", "node": "Worker nodes"}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        key = str(node.get("node_class") or "-").strip().lower() or "-"
        grouped.setdefault(key, []).append(node)
    ordered: list[dict[str, Any]] = []
    for key in ("link", "submit", "node"):
        items = grouped.pop(key, [])
        if items:
            ordered.append({"key": key, "label": labels[key], "nodes": items})
    for key in sorted(grouped):
        items = grouped[key]
        if items:
            ordered.append({"key": key, "label": f"{key.title()} nodes", "nodes": items})
    return ordered


def _summarize_nodes_by_class(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {"link": "Link", "submit": "Submit", "node": "Worker"}
    summary_map: dict[str, dict[str, Any]] = {}
    for key in ("link", "submit", "node"):
        summary_map[key] = {
            "key": key,
            "label": labels[key],
            "total": 0,
            "ready": 0,
            "busy": 0,
            "down": 0,
        }
    for node in nodes:
        key = str(node.get("node_class") or "-").strip().lower() or "-"
        entry = summary_map.setdefault(
            key,
            {
                "key": key,
                "label": key.title() if key != "-" else "Other",
                "total": 0,
                "ready": 0,
                "busy": 0,
                "down": 0,
            },
        )
        entry["total"] += 1
        bucket = _node_status_bucket(node)
        entry[bucket] += 1
    ordered = [summary_map[key] for key in ("link", "submit", "node")]
    ordered.extend(
        summary_map[key]
        for key in sorted(summary_map)
        if key not in {"link", "submit", "node"} and summary_map[key]["total"] > 0
    )
    return ordered


def _node_view(node: dict[str, Any], *, include_private: bool = True) -> dict[str, Any]:
    resources = node.get("resources") if isinstance(node.get("resources"), dict) else {}
    allocations = node.get("allocations") if isinstance(node.get("allocations"), dict) else {}
    alloc_items = allocations.get("items") if isinstance(allocations.get("items"), list) else []
    running_jobs = (
        allocations.get("running_jobs")
        if isinstance(allocations.get("running_jobs"), list)
        else []
    )
    alloc_count = int(allocations.get("count") or 0)
    visible_allocations = allocations
    visible_alloc_items = alloc_items
    visible_running_jobs = running_jobs
    if not include_private:
        visible_allocations = {
            "count": alloc_count,
            "running_jobs": [],
            "items": [],
        }
        visible_alloc_items = []
        visible_running_jobs = []
    return {
        "name": node.get("name") or node.get("node_name") or node.get("id") or "-",
        "id": node.get("id") or "-",
        "status": node.get("status") or "unknown",
        "node_class": node.get("node_class") or "-",
        "device_type": node.get("device_type") or "-",
        "resources": resources,
        "allocations": visible_allocations,
        "alloc_count": alloc_count,
        "running_job_count": len(visible_running_jobs),
        "running_jobs": ", ".join(str(job_id) for job_id in visible_running_jobs) or "-",
        "alloc_summary": ", ".join(
            sorted(
                str(alloc.get("job_id") or alloc.get("id") or "-")
                for alloc in visible_alloc_items
                if isinstance(alloc, dict)
            )
        ) or "-",
    }



def _arg_view(arg: Any, index: int) -> dict[str, Any]:
    raw = str(arg)
    if raw.startswith("--") and "=" in raw:
        name, value = raw.split("=", 1)
        return {"index": index, "kind": "option", "name": name, "value": value, "raw": raw}
    if raw.startswith("--"):
        return {"index": index, "kind": "flag", "name": raw, "value": "", "raw": raw}
    if raw.startswith("-") and len(raw) > 1:
        return {"index": index, "kind": "switch", "name": raw, "value": "", "raw": raw}
    return {"index": index, "kind": "value", "name": raw, "value": "", "raw": raw}


def _job_entries_view(jobs: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for job_name, info in jobs.items():
        role = _job_role_view(str(job_name))
        if not isinstance(info, dict):
            entries.append(
                {
                    "name": str(job_name),
                    "kind": role["kind"],
                    "role_label": role["label"],
                    "order": role["order"],
                    "summary": str(info),
                    "job_ids": [],
                    "tasks": [],
                    "fields": [],
                    "log_job": role["log_job"],
                    "log_task": "",
                    "primary_job_id": "",
                    "has_details": False,
                }
            )
            continue
        job_ids: list[str] = []
        if isinstance(info.get("job_id"), str):
            job_ids.append(info["job_id"])
        if isinstance(info.get("job_ids"), list):
            job_ids.extend(str(item) for item in info["job_ids"] if isinstance(item, str))
        tasks: list[str] = []
        if isinstance(info.get("task"), str):
            tasks.append(info["task"])
        if isinstance(info.get("tasks"), list):
            tasks.extend(str(item) for item in info["tasks"] if isinstance(item, str))
        fields: list[dict[str, str]] = []
        for key in sorted(info):
            if key in {"job_id", "job_ids", "task", "tasks"}:
                continue
            value = info[key]
            if isinstance(value, list):
                rendered = ", ".join(str(item) for item in value)
            elif isinstance(value, dict):
                rendered = ", ".join(f"{k}={v}" for k, v in sorted(value.items()))
            else:
                rendered = str(value)
            fields.append({"label": key.replace("_", " "), "value": rendered})
        summary_bits: list[str] = []
        if job_ids:
            summary_bits.append(f"{len(job_ids)} job id" + ("" if len(job_ids) == 1 else "s"))
        if tasks:
            summary_bits.append(f"{len(tasks)} task" + ("" if len(tasks) == 1 else "s"))
        entries.append(
            {
                "name": str(job_name),
                "kind": role["kind"],
                "role_label": role["label"],
                "order": role["order"],
                "summary": ", ".join(summary_bits) or "No mapping details",
                "job_ids": job_ids,
                "tasks": tasks,
                "fields": fields,
                "log_job": role["log_job"],
                "log_task": tasks[0] if len(tasks) == 1 else "",
                "primary_job_id": job_ids[0] if job_ids else "",
                "has_details": bool(fields),
            }
        )
    entries.sort(key=lambda item: (item["order"], item["name"]))
    return entries


def _job_role_view(job_name: str) -> dict[str, Any]:
    mapping = {
        "submit": {"kind": "submit", "label": "Submit", "order": 0, "log_job": "submit"},
        "superlink": {"kind": "superlink", "label": "SuperLink", "order": 1, "log_job": "superlink"},
        "supernodes": {"kind": "supernodes", "label": "Supernodes", "order": 2, "log_job": "supernodes"},
        "superexec_serverapp": {
            "kind": "serverapp",
            "label": "Serverapp",
            "order": 3,
            "log_job": "superexec_serverapp",
        },
        "superexec_clientapps": {
            "kind": "clientapps",
            "label": "Clientapps",
            "order": 4,
            "log_job": "superexec_clientapps",
        },
    }
    if job_name in mapping:
        return mapping[job_name]
    return {
        "kind": _slug(job_name),
        "label": job_name.replace("_", " "),
        "order": 99,
        "log_job": job_name,
    }


def _submission_list_command(status_filter: str) -> str:
    return {
        "active": "fedctl submit ls --active",
        "completed": "fedctl submit ls --completed",
        "failed": "fedctl submit ls --failed",
        "cancelled": "fedctl submit ls --cancelled",
        "all": "fedctl submit ls --all",
    }.get(status_filter, "fedctl submit ls --active")


def _inventory_command() -> str:
    return "fedctl submit inventory"


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _fmt_dt(value: Any) -> dict[str, str]:
    dt = _parse_dt(value)
    if dt is None:
        label = str(value) if value is not None else "-"
        return {"label": label, "iso": ""}
    return {"label": dt.strftime("%Y-%m-%d %H:%M:%S"), "iso": dt.isoformat()}


def _fmt_queue_wait(created: Any, started: Any, status: Any) -> str:
    dt_created = _parse_dt(created)
    if dt_created is None:
        return "-"
    dt_started = _parse_dt(started)
    if dt_started is not None:
        return _fmt_duration_between(dt_created, dt_started)
    if str(status or "").lower() in {"queued", "blocked"}:
        return _fmt_duration_between(dt_created, _now_like(dt_created))
    return "-"


def _fmt_runtime(started: Any, finished: Any, status: Any) -> str:
    dt_started = _parse_dt(started)
    if dt_started is None:
        return "-"
    dt_finished = _parse_dt(finished)
    if dt_finished is not None:
        return _fmt_duration_between(dt_started, dt_finished)
    if str(status or "").lower() in {"running"}:
        return _fmt_duration_between(dt_started, _now_like(dt_started))
    return "-"


def _now_like(dt: datetime) -> datetime:
    return datetime.now(dt.tzinfo)


def _fmt_duration_between(dt_start: datetime, dt_end: datetime) -> str:
    if dt_start is None:
        return "-"
    delta = dt_end - dt_start
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        return "-"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _render_logs_html(content: str | None) -> str:
    if not content:
        return '<span class="log-empty">No log content available for this selection.</span>'
    if _ANSI_RE.search(content):
        return _ANSI_CONVERTER.convert(content, full=False)
    return escape(content)
