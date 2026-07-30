from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AgentFlow API"
    database_url: str = "sqlite:///./agentflow.db"
    jwt_secret: str = "dev-only-change-me"
    access_token_minutes: int = 720
    llm_mode: str = "mock"
    execution_mode: str = "inline"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
