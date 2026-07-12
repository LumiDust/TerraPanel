from pathlib import Path

import pytest

from terrapanel.path_policy import PathOutsideRootError, PathPolicy


def test_resolves_path_inside_root(tmp_path: Path) -> None:
    policy = PathPolicy(tmp_path / "servers")
    policy.ensure_root()

    resolved = policy.resolve("primary/worlds/main.wld")

    assert resolved == policy.root / "primary" / "worlds" / "main.wld"


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    policy = PathPolicy(tmp_path / "servers")

    with pytest.raises(PathOutsideRootError):
        policy.resolve("../outside.txt")


def test_rejects_absolute_path_outside_root(tmp_path: Path) -> None:
    policy = PathPolicy(tmp_path / "servers")

    with pytest.raises(PathOutsideRootError):
        policy.resolve(tmp_path / "outside.txt")
