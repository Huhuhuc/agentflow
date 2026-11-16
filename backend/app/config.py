from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from pydantic import model_validator


class Settings(BaseSettings):
    app_name: str = "AgentFlow API"
    database_url: str = "sqlite:///./agentflow.db"
    jwt_secret: str = "dev-only-change-me"
    access_token_minutes: int = 720
    demo_mode: bool = True
    llm_mode: str = "mock"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_timeout: float = 30.0
    llm_max_retries: int = 2
    llm_retry_backoff: float = 0.5
    execution_mode: str = "inline"
    embedding_model_path: str = ""
    embedding_revision: str = ""
    retrieval_mode: str = "lexical"
    retrieval_abstention_threshold: float | None = None
    retrieval_min_index_coverage: float = 1.0
    retrieval_embedding_timeout_seconds: float = 5.0
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=Path(__file__).resolve().parents[1] / ".env", env_file_encoding="utf-8-sig", extra="ignore")

    @model_validator(mode="after")
    def production_secret(self):
        if not self.demo_mode and (len(self.jwt_secret)<32 or self.jwt_secret in {"dev-only-change-me","change-this-in-production"}):
            raise ValueError("DEMO_MODE=false requires a private JWT_SECRET of at least 32 characters")
        return self

    @model_validator(mode="after")
    def retrieval_config(self):
        if self.retrieval_mode not in {"lexical", "hybrid"}:
            raise ValueError("RETRIEVAL_MODE must be lexical or hybrid")
        if not 0 < self.retrieval_min_index_coverage <= 1:
            raise ValueError("RETRIEVAL_MIN_INDEX_COVERAGE must be between 0 and 1")
        if self.retrieval_abstention_threshold is not None and self.retrieval_abstention_threshold < 0:
            raise ValueError("RETRIEVAL_ABSTENTION_THRESHOLD must be non-negative")
        if self.retrieval_embedding_timeout_seconds <= 0:
            raise ValueError("RETRIEVAL_EMBEDDING_TIMEOUT_SECONDS must be positive")
        return self


settings = Settings()
