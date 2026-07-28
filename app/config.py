from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Base de données
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/moov_africa_db_test"
    SYNC_DATABASE_URL: str = "postgresql+psycopg2://postgres:password@localhost:5432/moov_africa_db_test"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # Chemins des modèles ML
    ML_MODELS_PATH: str = "./models"

    # Seuils ML
    SCORE_THRESHOLD_CHURN: float = 0.5
    SCORE_THRESHOLD_FRAUDE: float = 0.5

    # Réentraînement
    RETRAIN_INTERVAL_MINUTES: int = 15

    # JWT
    JWT_SECRET_KEY: str = "moov-africa-togo-ml-secret-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60  # 1 heure
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    class Config:
        env_file = ".env"


settings = Settings()
