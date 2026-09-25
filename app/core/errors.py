class ApplicationError(RuntimeError):
    """Base class for expected application failures."""


class ConfigurationError(ApplicationError):
    """Raised when configuration is incomplete."""


class DataValidationError(ApplicationError):
    """Raised when external or user data violates a domain invariant."""


class InvalidRunTransition(ApplicationError):
    """Raised when a completed collection run is mutated."""


class KamisApiError(ApplicationError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.api_message = message
        super().__init__(f"KAMIS API error code={code}: {message}")


class KamisAuthenticationError(KamisApiError):
    """Raised for KAMIS error code 900."""


class KamisNoDataError(KamisApiError):
    """Raised for KAMIS error code 001."""


class StorageError(ApplicationError):
    """Raised when durable CSV persistence fails."""


class CollectionAlreadyRunning(ApplicationError):
    """Raised when a second collection starts while one is active."""


class ShoppingAccessBlocked(ApplicationError):
    """Raised when a shopping platform refuses automated page access."""

    def __init__(self, status_code: int | None, reason: str) -> None:
        self.status_code = status_code
        self.reason = reason
        detail = f"HTTP {status_code}" if status_code is not None else reason
        super().__init__(f"shopping access blocked: {detail}")
