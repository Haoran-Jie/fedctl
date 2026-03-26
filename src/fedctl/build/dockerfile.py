from __future__ import annotations

TORCH_CPU_INDEX_URL = "https://download.pytorch.org/whl/cpu"
TORCH_CPU_VERSION = "2.7.0+cpu"
TORCHVISION_CPU_VERSION = "0.22.0"


def render_dockerfile(flwr_version: str) -> str:
    return (
        f"FROM flwr/superexec:{flwr_version}\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY pyproject.toml .\n"
        "USER root\n"
        "RUN apt-get update \\\n"
        "  && apt-get install -y --no-install-recommends iproute2 \\\n"
        "  && rm -rf /var/lib/apt/lists/* \\\n"
        "  && mkdir -p /app/.flwr \\\n"
        "  && chown -R app:app /app/.flwr \\\n"
        "  && if grep -Eq '^[[:space:]]*\"torch([<>=!~].*)?\"' pyproject.toml; then \\\n"
        f"       python -m pip install -U --no-cache-dir --index-url {TORCH_CPU_INDEX_URL} \\\n"
        f"         torch=={TORCH_CPU_VERSION} torchvision=={TORCHVISION_CPU_VERSION}; \\\n"
        "     fi \\\n"
        "  && sed -i 's/.*flwr\\[simulation\\].*//' pyproject.toml \\\n"
        "  && sed -i '/.*\"torch\\([<>=!~].*\\)\".*/d' pyproject.toml \\\n"
        "  && sed -i '/.*\"torchvision\\([<>=!~].*\\)\".*/d' pyproject.toml \\\n"
        "  && python -m pip install -U --no-cache-dir .\n"
        "USER app\n"
        "\n"
        'ENTRYPOINT ["flower-superexec"]\n'
    )


def render_supernode_dockerfile(flwr_version: str) -> str:
    return (
        f"FROM flwr/supernode:{flwr_version}\n"
        "\n"
        "USER root\n"
        "RUN if command -v apt-get >/dev/null 2>&1; then \\\n"
        "      apt-get update \\\n"
        "      && apt-get install -y --no-install-recommends iproute2 \\\n"
        "      && rm -rf /var/lib/apt/lists/*; \\\n"
        "    elif command -v apk >/dev/null 2>&1; then \\\n"
        "      apk add --no-cache iproute2; \\\n"
        "    else \\\n"
        "      echo \"No supported package manager found (apt-get/apk)\"; exit 1; \\\n"
        "    fi\n"
    )
