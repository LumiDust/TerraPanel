from pydantic import BaseModel


class SpamCheckStatus(BaseModel):
    config_path: str | None
    secure_value: str | None
    secure_configured: bool
    secure_enabled: bool | None
    launch_script_path: str
    launch_script_inspected: bool
    secure_launch_argument: bool
    projectile_spam_matches: int
    projectile_spam_sources: list[str]
    protection_disabled: bool
