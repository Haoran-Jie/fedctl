from __future__ import annotations


def render_dockerfile(flwr_version: str) -> str:
    return (
        f"FROM flwr/superexec:{flwr_version}\n"
        "\n"
        "WORKDIR /app\n"
        "\n"
        "COPY pyproject.toml .\n"
        "USER root\n"
        "RUN mkdir -p /app/.flwr \\\n"
        "  && chown -R app:app /app/.flwr \\\n"
        "  && sed -i 's/.*flwr\\[simulation\\].*//' pyproject.toml \\\n"
        "  && python -m pip install -U --no-cache-dir .\n"
        "USER app\n"
        "\n"
        'ENTRYPOINT ["flower-superexec"]\n'
    )
