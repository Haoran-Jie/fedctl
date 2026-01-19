"""Module entrypoint for `python -m fedctl`."""

from .cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
