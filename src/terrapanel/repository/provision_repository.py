import os
from pathlib import Path
from threading import RLock

from terrapanel.domain.provisioning import ProvisionSnapshot


class ProvisionRepository:
    def __init__(self, metadata_file: Path) -> None:
        self._metadata_file = metadata_file
        self._lock = RLock()

    def get(self) -> ProvisionSnapshot | None:
        with self._lock:
            if not self._metadata_file.is_file():
                return None
            return ProvisionSnapshot.model_validate_json(
                self._metadata_file.read_text(encoding="utf-8")
            )

    def save(self, snapshot: ProvisionSnapshot) -> ProvisionSnapshot:
        with self._lock:
            self._metadata_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._metadata_file.with_suffix(".tmp")
            temporary.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, self._metadata_file)
            return snapshot
