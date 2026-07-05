from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Ajoutez cette ligne :
    sync_database_url: str

    # Base de données
    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/moov_africa_db_test"

    # CORS
    CORS_ORIGINS: str = "http://localhost:3000"

    # Chemins des modèles ML
    ML_MODELS_PATH: str = "./models"

    # Seuils de décision (appliqués par le backend lors de l'inférence)
    SCORE_THRESHOLD_CHURN: float = 0.5
    SCORE_THRESHOLD_FRAUDE: float = 0.5

    # Intervalle du job de réentraînement (minutes)
    RETRAIN_INTERVAL_MINUTES: int = 15

    class Config:
        env_file = ".env"


settings = Settings()
