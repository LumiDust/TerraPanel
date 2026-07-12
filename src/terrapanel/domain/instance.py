from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InstanceRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: Literal["primary"] = "primary"
    name: str = Field(min_length=1, max_length=80)
    root_dir: Path
    install_dir: Path
    launch_script: Path
    config_file: Path
    created_at: datetime
    updated_at: datetime


class InstanceAssociation(BaseModel):
    name: str = Field(default="Primary Server", min_length=1, max_length=80)
    root_dir: str
