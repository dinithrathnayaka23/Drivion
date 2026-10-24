"""Secret values (API keys) loaded from environment variables or a local ``.env``.

Secrets are wrapped in ``SecretStr`` so that printing or logging the object
shows ``**********`` instead of the real value. Call ``.get_secret_value()``
only at the exact point where the key is handed to the provider's SDK.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DRIVION_",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    porcupine_access_key: SecretStr | None = None
    llm_api_key: SecretStr | None = None

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_missing(cls, value: object) -> object:
        # ".env.example" ships with empty values; treat them as "not configured".
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def values(self) -> list[str]:
        """Return the raw secret strings, used only by the log redaction filter."""
        found = []
        for name in type(self).model_fields:
            secret = getattr(self, name)
            if secret is not None:
                found.append(secret.get_secret_value())
        return found


def load_secrets(env_file: Path | None) -> Secrets:
    """Real environment variables take precedence over the ``.env`` file."""
    if env_file is not None and env_file.exists():
        return Secrets(_env_file=env_file)
    return Secrets(_env_file=None)
