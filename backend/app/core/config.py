from pathlib import Path
from typing import Literal

from pydantic import (
    HttpUrl,
    NonNegativeInt,
    PositiveInt,
    PostgresDsn,
    SecretStr,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_REPOSITORY_ROOT / ".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    API_PREFIX: str = "/api"
    FASTAPI_ENV: Literal["development", "production"] = "production"

    PROJECT_NAME: str = "LangGraph Agentic RAG"

    DATABASE_URL: PostgresDsn

    SUPABASE_URL: HttpUrl
    SUPABASE_PUBLISHABLE_KEY: SecretStr
    SUPABASE_SECRET_KEY: SecretStr
    SUPABASE_STORAGE_BUCKET: str = "documents"

    OPENAI_API_KEY: SecretStr
    OPENAI_MAIN_MODEL: str = "gpt-5.6-terra"
    OPENAI_GROUNDING_MODEL: str = "gpt-5.6-terra"
    OPENAI_MEMORY_EXTRACTION_MODEL: str = "gpt-5.6-luna"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    COHERE_API_KEY: SecretStr
    TAVILY_API_KEY: SecretStr

    LANGFUSE_PUBLIC_KEY: SecretStr
    LANGFUSE_SECRET_KEY: SecretStr
    LANGFUSE_BASE_URL: HttpUrl

    DOCUMENT_CHUNK_SIZE: PositiveInt = 1000
    DOCUMENT_CHUNK_OVERLAP: NonNegativeInt = 200
    MAX_PDF_UPLOAD_SIZE_BYTES: PositiveInt = 10 * 1024 * 1024

    @property
    def sqlalchemy_database_url(self) -> str:
        return str(self.DATABASE_URL).replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )


settings = Settings()
