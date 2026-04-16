#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FEDCTL_BIN="${ROOT_DIR}/.venv/bin/fedctl"
APP_PATH="apps/fedctl_research"
BASE_CONFIG="apps/fedctl_research/experiment_configs/compute_heterogeneity/main/appliances_energy_mlp/noniid/heterofl.toml"
REPO_CONFIG=".fedctl/main_compute_heterogeneity.yaml"
SUBMIT_IMAGE="128.232.61.111:5000/fedctl-submit:latest"
SEED="1337"
WANDB_GROUP="compute_heterogeneity-tuning-appliances_energy_mlp-noniid-heterofl"

LOCAL_EPOCHS=(1 3 5)
LEARNING_RATES=(0.001 0.003 0.01)

MODE="print"
if [[ "${1:-}" == "--submit" ]]; then
  MODE="submit"
fi

submit_one() {
  local local_epochs="$1"
  local learning_rate="$2"
  local lr_token
  lr_token="$(printf '%s' "${learning_rate}" | tr '.' 'p')"
  local exp_name="appliances-energy-heterofl-n20-seed${SEED}-e${local_epochs}-lr${lr_token}"
  local -a cmd=(
    "${FEDCTL_BIN}" submit run "${APP_PATH}"
    --experiment-config "${BASE_CONFIG}"
    --repo-config "${REPO_CONFIG}"
    --submit-image "${SUBMIT_IMAGE}"
    --seed "${SEED}"
    --exp "${exp_name}"
    --run-config-override "local-epochs=${local_epochs}"
    --run-config-override "learning-rate=${learning_rate}"
    --run-config-override "wandb.group=${WANDB_GROUP}"
    --no-stream
  )

  printf '\n==> %s\n' "${exp_name}"
  printf '%q ' "${cmd[@]}"
  printf '\n'

  if [[ "${MODE}" == "submit" ]]; then
    (
      cd "${ROOT_DIR}"
      "${cmd[@]}"
    )
  fi
}

for local_epochs in "${LOCAL_EPOCHS[@]}"; do
  for learning_rate in "${LEARNING_RATES[@]}"; do
    submit_one "${local_epochs}" "${learning_rate}"
  done
done
