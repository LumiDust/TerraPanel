import stat
import zipfile
from pathlib import Path

import pytest

from terrapanel.config import Settings
from terrapanel.domain.errors import DomainValidationError, ResourceNotFoundError
from terrapanel.services.container import ServiceContainer


def test_backup_and_restore_round_trip(
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    world = instance_root / "Worlds" / "Example.wld"
    mod_world = world.with_suffix(".twld")
    world.write_bytes(b"original world")
    mod_world.write_bytes(b"original mod world")
    (instance_root / "Mods" / "enabled.json").write_text('["ExampleMod"]\n', encoding="utf-8")

    backup = services.backups.create("manual")
    world.write_bytes(b"changed")
    mod_world.unlink()
    (instance_root / "Mods" / "enabled.json").write_text("[]\n", encoding="utf-8")

    restored = services.backups.restore(backup.id)

    assert restored.id == backup.id
    assert world.read_bytes() == b"original world"
    assert mod_world.read_bytes() == b"original mod world"
    assert "ExampleMod" in (instance_root / "Mods" / "enabled.json").read_text()


def test_resolves_and_deletes_backup_archive(
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    (instance_root / "Worlds" / "Example.wld").write_bytes(b"world")
    backup = services.backups.create("managed")
    archive = services.backups.archive_path(backup.id)

    assert archive.is_file()

    services.backups.delete(backup.id)

    assert not archive.exists()
    with pytest.raises(ResourceNotFoundError):
        services.backups.archive_path(backup.id)


def test_rejects_zip_slip_backup(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    archive = app_settings.storage.backups_dir / "malicious.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("../escape.txt", "unsafe")
        file.writestr("Worlds/Example.wld", "world")

    with pytest.raises(DomainValidationError, match="Unsafe path"):
        services.backups.restore("malicious")

    assert not (instance_root.parent / "escape.txt").exists()


def test_rejects_corrupt_backup(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    archive = app_settings.storage.backups_dir / "corrupt.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"not a zip archive")

    with pytest.raises(DomainValidationError, match="archive is invalid"):
        services.backups.restore("corrupt")


def test_rejects_unknown_backup_entry(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    archive = app_settings.storage.backups_dir / "unknown.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr("Worlds/Example.wld", "world")
        file.writestr("unexpected.txt", "unexpected")

    with pytest.raises(DomainValidationError, match="Unexpected file"):
        services.backups.restore("unknown")


def test_rejects_symbolic_link_backup_entry(
    app_settings: Settings,
    instance_root: Path,
    services: ServiceContainer,
) -> None:
    archive = app_settings.storage.backups_dir / "symlink.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    link = zipfile.ZipInfo("Worlds/Example.wld")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(archive, "w") as file:
        file.writestr(link, "../../outside.wld")

    with pytest.raises(DomainValidationError, match="Symbolic links"):
        services.backups.restore("symlink")
