import os
from datetime import UTC, datetime
from pathlib import Path

from terrapanel.domain.errors import DomainValidationError, NotConfiguredError
from terrapanel.domain.instance import InstanceAssociation, InstanceRecord
from terrapanel.path_policy import PathOutsideRootError, PathPolicy
from terrapanel.repository.instance_repository import InstanceRepository

_DEFAULT_SERVER_CONFIG = """# TerraPanel instance configuration
# Select an existing world through the API or configure autocreate before starting.
maxplayers=8
port=7777
secure=1
upnp=0
priority=1
"""


class InstanceService:
    def __init__(self, repository: InstanceRepository, server_paths: PathPolicy) -> None:
        self._repository = repository
        self._server_paths = server_paths

    def get(self) -> InstanceRecord | None:
        instance = self._repository.get()
        if instance is None:
            return None
        return self._validate_record(instance)

    def require(self) -> InstanceRecord:
        instance = self.get()
        if instance is None:
            raise NotConfiguredError("No tModLoader server instance is associated")
        return instance

    def associate(self, association: InstanceAssociation) -> InstanceRecord:
        try:
            root_dir = self._server_paths.resolve(association.root_dir, must_exist=True)
        except (FileNotFoundError, PathOutsideRootError) as error:
            raise DomainValidationError(str(error)) from error

        install_dir, launch_script, config_file = self._prepare_layout(root_dir)

        previous = self._repository.get()
        now = datetime.now(UTC)
        instance = InstanceRecord(
            name=association.name,
            root_dir=root_dir,
            install_dir=install_dir,
            launch_script=launch_script,
            config_file=config_file,
            created_at=previous.created_at if previous else now,
            updated_at=now,
        )
        return self._repository.save(instance)

    def remove(self) -> None:
        self._repository.delete()

    def prepare_root(self, candidate: str | Path) -> Path:
        try:
            root_dir = self._resolve_managed(self._server_paths.root, candidate)
        except (FileNotFoundError, PathOutsideRootError) as error:
            raise DomainValidationError(str(error)) from error
        if root_dir.exists() and not root_dir.is_dir():
            raise DomainValidationError(f"Instance root is not a directory: {root_dir}")
        root_dir.mkdir(parents=True, exist_ok=True)
        return self._resolve_managed(self._server_paths.root, root_dir, must_exist=True)

    def root_policy(self) -> PathPolicy:
        return PathPolicy(self.require().root_dir)

    def resolve_in_root(self, candidate: str | Path, *, must_exist: bool = False) -> Path:
        try:
            return self._resolve_managed(
                self.require().root_dir,
                candidate,
                must_exist=must_exist,
            )
        except (FileNotFoundError, PathOutsideRootError) as error:
            raise DomainValidationError(str(error)) from error

    def _validate_record(self, instance: InstanceRecord) -> InstanceRecord:
        try:
            root_dir = self._server_paths.resolve(instance.root_dir, must_exist=True)
        except (FileNotFoundError, PathOutsideRootError) as error:
            raise DomainValidationError(f"The associated instance is invalid: {error}") from error

        install_dir, launch_script, config_file = self._prepare_layout(root_dir)
        expected = (root_dir, install_dir, launch_script, config_file)
        actual = (
            instance.root_dir,
            instance.install_dir,
            instance.launch_script,
            instance.config_file,
        )
        if actual != expected:
            raise DomainValidationError(
                "The stored instance paths do not match the configured server directory"
            )
        return instance

    def _prepare_layout(self, root_dir: Path) -> tuple[Path, Path, Path]:
        if not root_dir.is_dir():
            raise DomainValidationError(f"Instance root is not a directory: {root_dir}")

        install_dir = self._resolve_managed(root_dir, "server")
        if not install_dir.is_dir():
            raise DomainValidationError(
                f"The tModLoader installation is incomplete: {install_dir}"
            )

        launch_script = self._resolve_managed(
            root_dir,
            "server/start-tModLoaderServer.sh",
        )
        assembly = self._resolve_managed(
            root_dir,
            "server/tModLoader.dll",
        )
        missing = [path for path in (launch_script, assembly) if not path.is_file()]
        if missing:
            formatted = ", ".join(str(path) for path in missing)
            raise DomainValidationError(f"The tModLoader installation is incomplete: {formatted}")

        for relative in ("Mods", "Worlds", "steamapps/workshop", "logs"):
            directory = self._resolve_managed(root_dir, relative)
            if directory.exists() and not directory.is_dir():
                raise DomainValidationError(f"Managed path is not a directory: {directory}")
            directory.mkdir(parents=True, exist_ok=True)
            self._resolve_managed(root_dir, relative, must_exist=True)

        config_file = self._resolve_managed(root_dir, "serverconfig.txt")
        if config_file.exists() and not config_file.is_file():
            raise DomainValidationError(f"Server config is not a file: {config_file}")
        if not config_file.exists():
            config_file.write_text(_DEFAULT_SERVER_CONFIG, encoding="utf-8")
        self._resolve_managed(root_dir, config_file, must_exist=True)
        return install_dir, launch_script, config_file

    @staticmethod
    def _resolve_managed(
        root_dir: Path,
        candidate: str | Path,
        *,
        must_exist: bool = False,
    ) -> Path:
        path = Path(candidate).expanduser()
        if not path.is_absolute():
            path = root_dir / path
        lexical = Path(os.path.abspath(path))

        try:
            relative = lexical.relative_to(root_dir)
        except ValueError as error:
            raise PathOutsideRootError(
                f"Path is outside the associated instance root: {candidate}"
            ) from error

        current = root_dir
        for part in relative.parts:
            current /= part
            if current.is_symlink() or current.is_junction():
                raise DomainValidationError(
                    f"Symbolic links and directory junctions are not allowed: {current}"
                )

        resolved = PathPolicy(root_dir).resolve(lexical, must_exist=must_exist)
        if resolved != lexical:
            raise DomainValidationError(f"Managed path resolves through a link: {candidate}")
        return resolved
