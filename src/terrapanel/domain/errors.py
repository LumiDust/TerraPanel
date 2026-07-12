class TerraPanelError(Exception):
    """Base class for expected domain failures."""


class NotConfiguredError(TerraPanelError):
    pass


class ResourceNotFoundError(TerraPanelError):
    pass


class ConflictError(TerraPanelError):
    pass


class DomainValidationError(TerraPanelError):
    pass


class UnsupportedPlatformError(TerraPanelError):
    pass
