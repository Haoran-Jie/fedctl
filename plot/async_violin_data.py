from __future__ import annotations

import csv
import json
import plistlib
import re
import sys
from dataclasses import dataclass

if sys.platform == 'darwin':
    _plistlib_loads = plistlib.loads

    def _safe_plistlib_loads(data, *args, **kwargs):
        payload = _plistlib_loads(data, *args, **kwargs)
        if isinstance(payload, list) and len(payload) == 1 and isinstance(payload[0], dict) and '_items' not in payload[0]:
            return [{'_items': []}]
        return payload

    plistlib.loads = _safe_plistlib_loads

import wandb

from common import TMP_DIR, cache_is_fresh, force_refresh_requested, plot_output_path, write_csv_plot

ENTITY = 'samueljie1-the-university-of-cambridge'
PROJECT = 'fedctl'
RAW_FILENAME = 'network_async_update_weights_raw.csv'
RAW_PATH = plot_output_path(RAW_FILENAME)
TMPDIR = TMP_DIR / 'wandb_network_async_participation_staleness'
MAX_STEPS = 60
STEP_TABLE_RE = re.compile(r'step_table_(\d+)_')


@dataclass(frozen=True)
class RunSpec:
    method: str
    buffer_size: int
    seed: int
    run_id: str
    source: str


@dataclass(frozen=True)
class UpdateRow:
    run_id: str
    method: str
    buffer_size: int
    seed: int
    source: str
    server_step: int
    client_trips_total: int
    node_id: str
    device_type: str
    staleness: int
    applied_weight: float


RUNS = (
    RunSpec('fedbuff', 5, 1337, 'f8r1yqsh', 'network_stressor_sweep'),
    RunSpec('fedbuff', 5, 1338, '3sduvg0n', 'network_stressor_sweep'),
    RunSpec('fedbuff', 5, 1339, 'w54p73te', 'network_stressor_sweep'),
    RunSpec('fedbuff', 10, 1337, 'j81afai0', 'network_main'),
    RunSpec('fedbuff', 10, 1338, 'kouohvbb', 'network_main'),
    RunSpec('fedbuff', 10, 1339, 'o7i4mdii', 'network_main'),
    RunSpec('fedstaleweight', 5, 1337, 'qjnt77fk', 'network_stressor_sweep'),
    RunSpec('fedstaleweight', 5, 1338, 'hmg55ujk', 'network_stressor_sweep'),
    RunSpec('fedstaleweight', 5, 1339, 'yk3uqpnh', 'network_stressor_sweep'),
    RunSpec('fedstaleweight', 10, 1337, 'wyc9rjxq', 'network_main'),
    RunSpec('fedstaleweight', 10, 1338, 'b0xxbbi7', 'network_main'),
    RunSpec('fedstaleweight', 10, 1339, '9qv2c0qb', 'network_main'),
)


def expected_seed_coverage() -> dict[str, dict[str, object]]:
    coverage: dict[str, dict[str, object]] = {}
    for spec in RUNS:
        key = f'{spec.method}_k{spec.buffer_size}'
        entry = coverage.setdefault(key, {'seeds': [], 'run_ids': []})
        entry['seeds'].append(spec.seed)
        entry['run_ids'].append(spec.run_id)
    for entry in coverage.values():
        entry['seeds'] = sorted(entry['seeds'])
    return coverage


def _table_sort_key(name: str) -> tuple[int, str]:
    match = STEP_TABLE_RE.search(name)
    return (int(match.group(1)) if match else 10**9, name)


def _parse_table_payload(payload_text: str, spec: RunSpec) -> list[UpdateRow]:
    payload = json.loads(payload_text)
    columns = [str(column) for column in payload['columns']]
    idx = {name: pos for pos, name in enumerate(columns)}
    required = {
        'server_step',
        'client_trips_total',
        'node_id',
        'device_type',
        'update_staleness_server_steps',
        'update_applied_weight',
    }
    missing = sorted(required.difference(idx))
    if missing:
        raise RuntimeError(f'{spec.run_id}: missing client-update columns {missing}')

    rows: list[UpdateRow] = []
    for raw in payload['data']:
        server_step = int(raw[idx['server_step']])
        if server_step > MAX_STEPS:
            continue
        rows.append(
            UpdateRow(
                run_id=spec.run_id,
                method=spec.method,
                buffer_size=spec.buffer_size,
                seed=spec.seed,
                source=spec.source,
                server_step=server_step,
                client_trips_total=int(raw[idx['client_trips_total']]),
                node_id=str(raw[idx['node_id']]),
                device_type=str(raw[idx['device_type']]).lower(),
                staleness=int(raw[idx['update_staleness_server_steps']]),
                applied_weight=float(raw[idx['update_applied_weight']]),
            )
        )
    return rows


def _fetch_run_rows(api: wandb.Api, spec: RunSpec) -> list[UpdateRow]:
    run = api.run(f'{ENTITY}/{PROJECT}/{spec.run_id}')
    outdir = TMPDIR / spec.run_id
    outdir.mkdir(parents=True, exist_ok=True)
    files = sorted(
        (remote for remote in run.files() if 'media/table/client_update/step_table' in remote.name),
        key=lambda remote: _table_sort_key(remote.name),
    )
    if not files:
        raise RuntimeError(f'{spec.run_id}: no client_update/step_table files found')

    rows: list[UpdateRow] = []
    seen: set[tuple[int, int, str]] = set()
    for remote in files:
        local_path = outdir / remote.name
        if local_path.exists() and not force_refresh_requested():
            payload_text = local_path.read_text()
        else:
            local = remote.download(root=str(outdir), replace=True)
            payload_text = local.read()
        for row in _parse_table_payload(payload_text, spec):
            dedupe_key = (row.server_step, row.client_trips_total, row.node_id)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(row)
        covered_steps = {row.server_step for row in rows if 1 <= row.server_step <= MAX_STEPS}
        if len(covered_steps) >= MAX_STEPS:
            break
    return rows


def _write_rows(rows: list[UpdateRow]) -> None:
    write_csv_plot(
        RAW_FILENAME,
        [
            'run_id',
            'method',
            'buffer_size',
            'seed',
            'source',
            'server_step',
            'client_trips_total',
            'node_id',
            'device_type',
            'staleness',
            'update_applied_weight',
        ],
        (
            [
                row.run_id,
                row.method,
                row.buffer_size,
                row.seed,
                row.source,
                row.server_step,
                row.client_trips_total,
                row.node_id,
                row.device_type,
                row.staleness,
                row.applied_weight,
            ]
            for row in rows
        ),
    )


def _load_rows() -> list[UpdateRow]:
    if not RAW_PATH.exists():
        raise FileNotFoundError(f'Missing raw data: {RAW_PATH}')
    rows: list[UpdateRow] = []
    with RAW_PATH.open(newline='') as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or 'seed' not in reader.fieldnames:
            return []
        for raw in reader:
            step = int(raw['server_step'])
            if step > MAX_STEPS:
                continue
            rows.append(
                UpdateRow(
                    run_id=raw['run_id'],
                    method=raw['method'],
                    buffer_size=int(raw['buffer_size']),
                    seed=int(raw['seed']),
                    source=raw['source'],
                    server_step=step,
                    client_trips_total=int(raw['client_trips_total']),
                    node_id=raw['node_id'],
                    device_type=raw['device_type'],
                    staleness=int(raw['staleness']),
                    applied_weight=float(raw['update_applied_weight']),
                )
            )
    return rows


def load_or_fetch_rows() -> list[UpdateRow]:
    if RAW_PATH.exists() and cache_is_fresh(RAW_PATH) and not force_refresh_requested():
        rows = _load_rows()
        run_ids = {spec.run_id for spec in RUNS}
        if {row.run_id for row in rows} == run_ids:
            return rows

    api = wandb.Api(timeout=60)
    rows: list[UpdateRow] = []
    for spec in RUNS:
        rows.extend(_fetch_run_rows(api, spec))
    _write_rows(rows)
    return rows
