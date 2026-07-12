from dataclasses import dataclass
from pathlib import Path


class PathOutsideRootError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PathPolicy:
    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.expanduser().resolve())

    def ensure_root(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root

    def resolve(self, candidate: str | Path, *, must_exist: bool = False) -> Path:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = self.root / path

        resolved = path.resolve(strict=must_exist)
        try:
            resolved.relative_to(self.root)
        except ValueError as error:
            raise PathOutsideRootError(
                f"Path is outside the configured server root: {candidate}"
            ) from error

        return resolved
