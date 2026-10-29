# BLOC A — Tables sources
from app.models.dim_forfait import DimForfait
from app.models.dim_client import DimClient
from app.models.dim_agent import DimAgent
from app.models.fact_conso import FactConsoMensuelle
from app.models.fact_evenement import FactEvenementServiceClient
from app.models.fact_transaction import FactTransactionAgent
from app.models.sample_target_churn import SampleTargetChurn

# BLOC B — Tables features ML
from app.models.features import FeaturesChurn, FeaturesSegmentation, FeaturesFraude

# BLOC C — Tables résultats ML
from app.models.predictions import (
    PredictionChurn, PredictionFraude, PredictionSegment, SegmentDefinition
)

# BLOC D — Tables de gestion
from app.models.management import ModelRun, ImportLog
