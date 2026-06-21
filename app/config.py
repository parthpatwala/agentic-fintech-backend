from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    stripe_api_key: str
    public_key_path: str = "keys/public_key.pem"

    @field_validator("stripe_api_key")
    @classmethod
    def stripe_key_must_be_test(cls, v: str) -> str:
        if not v.startswith("sk_test_") or len(v) <= len("sk_test_"):
            raise ValueError(
                "STRIPE_API_KEY must begin with 'sk_test_' and contain characters "
                "after the prefix — production keys are not permitted in this prototype"
            )
        return v
