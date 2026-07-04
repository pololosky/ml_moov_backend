"""
Chargement des modèles ML avec compatibilité sklearn 1.5 → 1.9.

Problème : les fichiers .pkl sauvegardés avec sklearn 1.5.x référencent des
modules internes (ex: sklearn.ensemble._loss) qui ont été déplacés dans
sklearn 1.6+ (ex: sklearn._loss). Python ne peut plus désérialiser ces fichiers.

Solution : on patche sys.modules AVANT que joblib/pickle tente les imports,
en créant des alias qui redirigent les anciens noms vers les nouveaux modules.
Le CompatUnpickler sert de filet de sécurité supplémentaire pour les cas
où le patch de sys.modules ne suffit pas.
"""
import io
import pickle
import joblib
import importlib
import sys
import types
from pathlib import Path
from typing import Any

MODELS_DIR = Path(__file__).parent.parent.parent / "models"

# ─── Remapping modules : anciens chemins → nouveaux (sklearn 1.5 → 1.9) ──────
# Format : "ancien.module" → "nouveau.module"
# Ces mappings sont injectés dans sys.modules avant tout chargement joblib.
MODULE_REMAPPING: dict[str, str] = {
    # _loss sorti de sklearn.ensemble vers sklearn._loss (sklearn 1.6)
    "sklearn.ensemble._loss":                          "sklearn._loss.loss",
    "sklearn.ensemble._gb_losses":                     "sklearn._loss.loss",
    "sklearn.ensemble._hist_gradient_boosting._loss":  "sklearn._loss.loss",
    # Modules top-level sans préfixe sklearn (très vieilles versions)
    "_loss":                                           "sklearn._loss.loss",
    # GradientBoosting : le module _gb lui-même existe encore, mais
    # joblib peut avoir du mal à l'importer selon l'environnement
    "sklearn.ensemble._gradient_boosting":             "sklearn.ensemble._gb",
}

# ─── Remapping attributs renommés entre versions ──────────────────────────────
ATTR_REMAPPING: dict[tuple[str, str], tuple[str, str]] = {
    ("sklearn._loss.loss", "LeastSquaresError"):    ("sklearn._loss.loss", "HalfSquaredError"),
    ("sklearn._loss.loss", "LeastAbsoluteError"):   ("sklearn._loss.loss", "AbsoluteError"),
    ("sklearn._loss.loss", "HuberLossFunction"):    ("sklearn._loss.loss", "HuberLoss"),
    ("sklearn._loss.loss", "QuantileLossFunction"): ("sklearn._loss.loss", "PinballLoss"),
    ("sklearn._loss.loss", "BinomialDeviance"):     ("sklearn._loss.loss", "HalfBinomialLoss"),
    ("sklearn._loss.loss", "MultinomialDeviance"):  ("sklearn._loss.loss", "HalfMultinomialLoss"),
}


def _patch_sys_modules() -> None:
    """
    Injecte des alias dans sys.modules pour que pickle trouve les anciens
    noms de modules sklearn même s'ils ont changé de chemin.
    Appelé au démarrage, avant tout chargement de pkl.
    """
    # 1. Pré-charger tous les modules sklearn courants qui peuvent être
    #    référencés par des pkl anciens, pour s'assurer qu'ils sont dans
    #    sys.modules avant que joblib/pickle tente de les importer
    modules_to_preload = [
        "sklearn._loss.loss",
        "sklearn._loss.link",
        "sklearn.ensemble._gb",
        "sklearn.ensemble._forest",
        "sklearn.tree._classes",
        "sklearn.tree._tree",
        "sklearn.linear_model._logistic",
        "sklearn.preprocessing._data",
    ]
    for mod_name in modules_to_preload:
        try:
            importlib.import_module(mod_name)
        except ImportError:
            pass

    # 2. Créer les alias pour les anciens noms
    for old_name, new_name in MODULE_REMAPPING.items():
        if old_name in sys.modules:
            continue
        try:
            real_module = importlib.import_module(new_name)
            sys.modules[old_name] = real_module
        except ImportError:
            proxy = types.ModuleType(old_name)
            sys.modules[old_name] = proxy
class CompatUnpickler(pickle.Unpickler):
    """
    Filet de sécurité : intercepte find_class pour les cas où le patch
    sys.modules n'a pas suffi (attributs renommés, etc.).
    """

    def find_class(self, module: str, name: str) -> Any:
        # Remapper le module si connu
        remapped_module = MODULE_REMAPPING.get(module, module)

        # Remapper l'attribut si le couple est connu
        remapped_name = name
        key = (remapped_module, name)
        if key in ATTR_REMAPPING:
            remapped_module, remapped_name = ATTR_REMAPPING[key]

        try:
            return super().find_class(remapped_module, remapped_name)
        except (ImportError, AttributeError):
            pass

        # Essai avec les noms originaux
        try:
            return super().find_class(module, name)
        except (ImportError, AttributeError):
            raise ModuleNotFoundError(
                f"Impossible de charger '{module}.{name}'. "
                f"Ce .pkl nécessite une version incompatible de scikit-learn. "
                f"Ré-entraînez votre modèle avec scikit-learn "
                f"{importlib.import_module('sklearn').__version__}."
            )


def _load_with_compat(path: Path) -> Any:
    """
    Charge un fichier .pkl :
    1. Patche sys.modules (résout 99% des incompatibilités de version)
    2. Utilise joblib.load (qui gère correctement le format multi-objets joblib)
    3. En cas d'échec, bascule sur CompatUnpickler en mode pickle direct
    """
    # Toujours patcher avant de charger
    _patch_sys_modules()

    import warnings
    try:
        from sklearn.exceptions import InconsistentVersionWarning
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=InconsistentVersionWarning)
            return joblib.load(path)
    except (ModuleNotFoundError, AttributeError, ImportError) as e:
        # Fallback : pickle direct via CompatUnpickler
        try:
            with open(path, "rb") as f:
                return CompatUnpickler(f).load()
        except Exception as e2:
            raise RuntimeError(
                f"Impossible de charger {path.name}.\n"
                f"Erreur joblib : {e}\n"
                f"Erreur pickle : {e2}\n"
                f"Solution : ré-entraînez votre modèle avec scikit-learn "
                f"{importlib.import_module('sklearn').__version__} "
                f"et sauvegardez un nouveau .pkl."
            ) from e2


def _load(case: str, filename: str) -> Any:
    path = MODELS_DIR / case / filename
    if not path.exists():
        raise FileNotFoundError(
            f"Fichier manquant : {path}. "
            f"Déposez votre fichier '{filename}' dans models/{case}/"
        )
    return _load_with_compat(path)


class MLModels:
    """Conteneur singleton pour tous les modèles chargés au démarrage."""

    def __init__(self):
        self.churn_model = None
        self.churn_scaler = None
        self.churn_features: list[str] = []
        self.churn_load_error: str | None = None

        self.segmentation_model = None
        self.segmentation_scaler = None
        self.segmentation_features: list[str] = []
        self.segmentation_load_error: str | None = None

        self.fraude_model = None
        self.fraude_scaler = None
        self.fraude_features: list[str] = []
        self.fraude_load_error: str | None = None

    def load_all(self):
        import sklearn
        import warnings
        from sklearn.exceptions import InconsistentVersionWarning

        print(f"[ML] scikit-learn {sklearn.__version__} détecté")

        for case in ("churn", "segmentation", "fraude"):
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        category=InconsistentVersionWarning,
                    )
                    model    = _load(case, "model.pkl")
                    scaler   = _load(case, "scaler.pkl")
                    features = _load(case, "features.pkl")

                setattr(self, f"{case}_model",    model)
                setattr(self, f"{case}_scaler",   scaler)
                setattr(self, f"{case}_features", features)
                setattr(self, f"{case}_load_error", None)

                print(f"[ML] ✓ Modèle '{case}' chargé ({len(features)} features)")

            except FileNotFoundError as e:
                msg = str(e)
                setattr(self, f"{case}_load_error", msg)
                print(f"[ML] ⚠  Modèle '{case}' absent : {msg}")

            except RuntimeError as e:
                # Erreur d'incompatibilité pkl — l'API démarre quand même
                msg = str(e)
                setattr(self, f"{case}_load_error", msg)
                print(f"[ML] ✗  Modèle '{case}' incompatible avec sklearn {sklearn.__version__}.")
                print(f"[ML]    → Ré-entraînez et sauvegardez un nouveau .pkl.")
                print(f"[ML]    Détail : {msg[:200]}")

            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                setattr(self, f"{case}_load_error", msg)
                print(f"[ML] ✗  Erreur inattendue pour '{case}' : {msg[:200]}")

    def status(self) -> dict:
        """Retourne l'état de chargement de chaque modèle (pour /health)."""
        result = {}
        for case in ("churn", "segmentation", "fraude"):
            model = getattr(self, f"{case}_model")
            error = getattr(self, f"{case}_load_error")
            result[case] = {
                "loaded": model is not None,
                "error": error,
            }
        return result


# Instance globale partagée entre les routes
# Le patch sys.modules est appliqué immédiatement à l'import de ce module
_patch_sys_modules()
ml_models = MLModels()
