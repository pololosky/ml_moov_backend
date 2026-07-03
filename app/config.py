from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:19082005@localhost:5432/moov_africa_db"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://postgres:19082005@localhost:5432/moov_africa_db"
    CORS_ORIGINS: str = "http://localhost:3000"

    class Config:
        env_file = ".env"


settings = Settings()
