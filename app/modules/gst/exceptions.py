"""GST-specific domain errors. They extend the repo's VyapaariException."""

from app.core.exceptions import VyapaariException


class SchemaValidationError(VyapaariException):
    """A generated JSON payload does not match its official schema."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message, "SCHEMA_INVALID")
        self.errors = errors or []


class SigningError(VyapaariException):
    """Signing, verifying or QR rendering failed."""

    def __init__(self, message: str):
        super().__init__(message, "SIGNING_FAILED")
