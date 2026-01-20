from __future__ import annotations


def render_dockerfile(flwr_version: str) -> str:
    return (
        f"FROM flwr/superexec:{flwr_version}\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY pyproject.toml .\n"
        "RUN sed -i 's/.*flwr\\[simulation\\].*//' pyproject.toml \\\n"
        "  && python -m pip install -U --no-cache-dir .\n"
        "\n"
        'ENTRYPOINT ["flower-superexec"]\n'
    )
