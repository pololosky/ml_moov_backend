"""
Utilitaires partagés entre les routers.
"""
from decimal import Decimal


def clean_row(row: dict) -> dict:
    """
    Convertit les types non-JSON-serialisables retournés par asyncpg.

    Problème : asyncpg retourne les colonnes NUMERIC de PostgreSQL tantôt
    comme Decimal Python, tantôt comme des str quand elles viennent d'une
    requête text() brute. FastAPI échoue à les sérialiser en JSON.

    Solution : forcer la conversion vers float ou int selon le contenu.
    """
    out = {}
    for k, v in row.items():
        if v is None:
            out[k] = None
        elif isinstance(v, Decimal):
            out[k] = float(v)
        elif isinstance(v, str):
            # asyncpg peut retourner NUMERIC/INT comme str dans certains cas
            stripped = v.strip()
            if stripped == "":
                out[k] = v
            else:
                try:
                    # Contient un point ou notation exponentielle → float
                    if "." in stripped or "e" in stripped.lower():
                        out[k] = float(stripped)
                    else:
                        # Tenter int, sinon garder str
                        out[k] = int(stripped)
                except ValueError:
                    out[k] = v
        else:
            out[k] = v
    return out


def clean_rows(rows: list[dict]) -> list[dict]:
    """Applique clean_row sur une liste de lignes."""
    return [clean_row(r) for r in rows]
