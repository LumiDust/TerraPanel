import argparse
from collections.abc import Sequence
from pathlib import Path

import uvicorn

from terrapanel.app import create_app
from terrapanel.config import HttpSettings, load_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the TerraPanel API server")
    parser.add_argument("--config", type=Path, help="Path to a YAML configuration file")
    parser.add_argument("--host", help="Override the configured bind address")
    parser.add_argument("--port", type=int, help="Override the configured HTTP port")
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    settings = load_settings(args.config)

    if args.host is not None or args.port is not None:
        settings = settings.model_copy(
            update={
                "http": HttpSettings(
                    bind_address=(
                        args.host if args.host is not None else settings.http.bind_address
                    ),
                    port=args.port if args.port is not None else settings.http.port,
                )
            }
        )

    uvicorn.run(
        create_app(settings),
        host=settings.http.bind_address,
        port=settings.http.port,
        log_level=settings.log_level,
    )
