import os
from pathlib import Path
from threading import RLock

from terrapanel.domain.instance import InstanceRecord


class InstanceRepository:
    def __init__(self, metadata_file: Path) -> None:
        self._metadata_file = metadata_file
        self._lock = RLock()

    def get(self) -> InstanceRecord | None:
        with self._lock:
            if not self._metadata_file.exists():
                return None
            content = self._metadata_file.read_text(encoding="utf-8")
            return InstanceRecord.model_validate_json(content)

    def save(self, instance: InstanceRecord) -> InstanceRecord:
        with self._lock:
            self._metadata_file.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._metadata_file.with_suffix(".tmp")
            temporary.write_text(instance.model_dump_json(indent=2), encoding="utf-8")
            os.replace(temporary, self._metadata_file)
            return instance

    def delete(self) -> None:
        with self._lock:
            self._metadata_file.unlink(missing_ok=True)
