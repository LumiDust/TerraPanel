from dataclasses import dataclass

from terrapanel.config import Settings
from terrapanel.path_policy import PathPolicy
from terrapanel.repository.instance_repository import InstanceRepository
from terrapanel.repository.provision_repository import ProvisionRepository
from terrapanel.services.backup_service import BackupService
from terrapanel.services.instance_service import InstanceService
from terrapanel.services.log_service import LogService
from terrapanel.services.mod_service import ModService
from terrapanel.services.official_installer import OfficialGithubInstaller
from terrapanel.services.process_manager import ProcessManager
from terrapanel.services.provisioning_service import ProvisioningService
from terrapanel.services.server_config_service import ServerConfigService
from terrapanel.services.world_service import WorldService


@dataclass(frozen=True, slots=True)
class ServiceContainer:
    instances: InstanceService
    process: ProcessManager
    server_config: ServerConfigService
    worlds: WorldService
    mods: ModService
    logs: LogService
    backups: BackupService
    provisioning: ProvisioningService


def build_services(settings: Settings) -> ServiceContainer:
    server_paths = PathPolicy(settings.storage.servers_dir)
    server_paths.ensure_root()
    repository = InstanceRepository(settings.storage.data_dir / "instance.json")
    instances = InstanceService(repository, server_paths)
    process = ProcessManager(instances)
    server_config = ServerConfigService(instances)
    provisioning = ProvisioningService(
        instances,
        server_config,
        process,
        OfficialGithubInstaller(),
        ProvisionRepository(settings.storage.data_dir / "provisioning.json"),
    )
    return ServiceContainer(
        instances=instances,
        process=process,
        server_config=server_config,
        worlds=WorldService(
            instances,
            server_config,
            process,
            max_upload_size=settings.worlds.max_upload_size,
        ),
        mods=ModService(instances, process, max_upload_size=settings.mods.max_upload_size),
        logs=LogService(instances),
        backups=BackupService(instances, process, settings.storage.backups_dir),
        provisioning=provisioning,
    )
