"""
Authentification JWT + RBAC — Moov Africa Togo ML Analytics

Rôles :
  marketing      → lecture dashboards, export CSV
  data_engineer  → import données, recalculs, maintenance
  admin          → tout (users, audit, config, + tout ce que data_engineer peut faire)

Flow :
  1. POST /api/auth/login  → { access_token, refresh_token, user }
  2. Toutes les routes protégées lisent Authorization: Bearer <token>
  3. POST /api/auth/logout  → révocation du token en base
  4. POST /api/auth/refresh → nouveau access_token via refresh_token
  5. GET  /api/auth/me      → profil de l'utilisateur connecté
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.config import settings
from app.database import get_db
from app.utils import clean_row

# ─── Router ──────────────────────────────────────────────────────────────────
router = APIRouter(prefix="/api/auth", tags=["Auth"])
bearer_scheme = HTTPBearer(auto_error=False)

# ─── Permissions par rôle ────────────────────────────────────────────────────
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "marketing": {
        "dashboard:read",
        "churn:read",
        "fraude:read",
        "segmentation:read",
        "export:csv",
    },
    "data_engineer": {
        "dashboard:read",
        "churn:read",
        "fraude:read",
        "segmentation:read",
        "import:data",
        "model:run",
    },
    "admin": {
        "dashboard:read",
        "churn:read",
        "fraude:read",
        "segmentation:read",
        "export:csv",
        "import:data",
        "model:run",
        "user:manage",
        "audit:read",
        "config:manage",
    },
}


# ─── Schémas Pydantic ────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # secondes
    user: dict


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    user_id: str
    email: str
    first_name: str
    last_name: str
    full_name: str
    role_code: str
    role_label: str
    permissions: list[str]


# ─── Helpers JWT ─────────────────────────────────────────────────────────────
def _create_token(data: dict, expires_delta: timedelta, token_type: str = "access") -> str:
    payload = data.copy()
    jti = str(uuid.uuid4())
    payload.update({
        "exp": datetime.now(timezone.utc) + expires_delta,
        "iat": datetime.now(timezone.utc),
        "jti": jti,
        "type": token_type,
    })
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalide : {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def _is_revoked(jti: str, db: AsyncSession) -> bool:
    result = await db.execute(
        text("SELECT is_token_revoked(:jti)"),
        {"jti": jti},
    )
    return result.scalar() or False


# ─── Dépendance principale : utilisateur courant ─────────────────────────────
async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Non authentifié. Fournissez un token Bearer.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = _decode_token(credentials.credentials)

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Type de token invalide")

    jti = payload.get("jti", "")
    if await _is_revoked(jti, db):
        raise HTTPException(status_code=401, detail="Token révoqué. Reconnectez-vous.")

    # Vérification expiration
    exp = payload.get("exp")
    if exp and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Token expiré")

    return {
        "user_id":    payload["sub"],
        "email":      payload["email"],
        "first_name": payload["first_name"],
        "last_name":  payload["last_name"],
        "role_code":  payload["role"],
        "role_label": payload.get("role_label", ""),
        "jti":        jti,
        "permissions": list(ROLE_PERMISSIONS.get(payload["role"], set())),
    }


# ─── Dépendances de permission ────────────────────────────────────────────────
def require_permission(permission: str):
    """Factory : retourne une dépendance FastAPI qui vérifie une permission."""
    async def dependency(current_user: dict = Depends(get_current_user)) -> dict:
        role = current_user["role_code"]
        if permission not in ROLE_PERMISSIONS.get(role, set()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission refusée. Rôle '{role}' ne peut pas : {permission}",
            )
        return current_user
    return dependency


# Dépendances nommées (utilisées dans les routers)
CurrentUser        = Annotated[dict, Depends(get_current_user)]
RequireDashboard   = Annotated[dict, Depends(require_permission("dashboard:read"))]
RequireImport      = Annotated[dict, Depends(require_permission("import:data"))]
RequireModelRun    = Annotated[dict, Depends(require_permission("model:run"))]
RequireExport      = Annotated[dict, Depends(require_permission("export:csv"))]
RequireUserManage  = Annotated[dict, Depends(require_permission("user:manage"))]
RequireAudit       = Annotated[dict, Depends(require_permission("audit:read"))]


# ─── Routes d'auth ───────────────────────────────────────────────────────────
@router.post("/login", response_model=TokenResponse, summary="Connexion utilisateur")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Authentifie l'utilisateur directement en Python (bcrypt via passlib).
    Évite les incompatibilités asyncpg/RETURN NEXT avec les fonctions PostgreSQL.
    """
    from bcrypt import checkpw
    import bcrypt as _bcrypt

    ip = request.client.host if request.client else "unknown"
    ua = request.headers.get("user-agent", "")

    # 1. Récupérer l'utilisateur depuis la DB
    result = await db.execute(
        text("""
            SELECT u.user_id, u.email, u.first_name, u.last_name,
                   u.password_hash, u.is_active, u.is_email_verified,
                   u.failed_login_count, u.locked_until,
                   u.preferred_language, u.timezone,
                   r.role_code, r.role_label
            FROM app_user u
            JOIN user_role r ON r.role_id = u.role_id
            WHERE u.email = :email
        """),
        {"email": body.email},
    )
    row = result.mappings().one_or_none()

    # Fonction helper : log d'échec
    async def log_failure(uid, reason: str):
        try:
            await db.execute(
                text("""INSERT INTO user_login_log (user_id, action, ip_address, user_agent, details)
                        VALUES (:uid, 'login_failure', CAST(:ip AS INET), :ua, :det)"""),
                {"uid": str(uid) if uid else None, "ip": ip, "ua": ua,
                 "det": f'{{"reason": "{reason}"}}'},
            )
            await db.commit()
        except Exception:
            pass

    if not row:
        await log_failure(None, "unknown_email")
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")

    user = clean_row(dict(row))

    if not user.get("is_active"):
        await log_failure(user["user_id"], "account_inactive")
        raise HTTPException(status_code=403, detail="Compte désactivé.")

    locked_until = user.get("locked_until")
    if locked_until:
        from datetime import timezone as tz
        if isinstance(locked_until, str):
            locked_until = datetime.fromisoformat(locked_until)
        if locked_until.replace(tzinfo=tz.utc) > datetime.now(tz.utc):
            raise HTTPException(status_code=403, detail="Compte temporairement verrouillé.")

    # 2. Vérifier le mot de passe avec bcrypt natif (compatible bcrypt 5.x)
    pwd_hash = user["password_hash"]
    if isinstance(pwd_hash, str):
        pwd_hash = pwd_hash.encode("utf-8")
    pwd_plain = body.password.encode("utf-8")

    if not checkpw(pwd_plain, pwd_hash):
        # Incrémenter le compteur d'échecs
        failed = (user.get("failed_login_count") or 0) + 1
        if failed >= 5:
            await db.execute(
                text("UPDATE app_user SET failed_login_count = :n, locked_until = NOW() + INTERVAL '30 minutes' WHERE user_id = CAST(:uid AS UUID)"),
                {"n": failed, "uid": str(user["user_id"])},
            )
        else:
            await db.execute(
                text("UPDATE app_user SET failed_login_count = :n, locked_until = NULL WHERE user_id = CAST(:uid AS UUID)"),
                {"n": failed, "uid": str(user["user_id"])},
            )
        await log_failure(user["user_id"], "wrong_password")
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect.")

    # 3. Mise à jour last_login
    await db.execute(
        text("UPDATE app_user SET last_login_at = NOW(), last_login_ip = CAST(:ip AS INET), failed_login_count = 0, locked_until = NULL WHERE user_id = CAST(:uid AS UUID)"),
        {"ip": ip, "uid": str(user["user_id"])},
    )
    await db.execute(
        text("INSERT INTO user_login_log (user_id, action, ip_address, user_agent) VALUES (CAST(:uid AS UUID), 'login_success', CAST(:ip AS INET), :ua)"),
        {"uid": str(user["user_id"]), "ip": ip, "ua": ua},
    )
    await db.commit()

    # Générer les tokens
    token_data = {
        "sub":        str(user["user_id"]),
        "email":      user["email"],
        "first_name": user["first_name"],
        "last_name":  user["last_name"],
        "role":       user["role_code"],
        "role_label": user["role_label"],
    }

    access_token  = _create_token(
        token_data,
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )
    refresh_token = _create_token(
        {"sub": str(user["user_id"]), "email": user["email"], "role": user["role_code"]},
        timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
        "refresh",
    )

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user={
            "user_id":    str(user["user_id"]),
            "email":      user["email"],
            "first_name": user["first_name"],
            "last_name":  user["last_name"],
            "full_name":  f"{user['first_name']} {user['last_name']}",
            "role_code":  user["role_code"],
            "role_label": user["role_label"],
            "permissions": list(ROLE_PERMISSIONS.get(user["role_code"], set())),
        },
    )


@router.post("/logout", summary="Déconnexion (révocation token)")
async def logout(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    ip = request.client.host if request and request.client else "unknown"
    jti = current_user["jti"]
    exp = datetime.now(timezone.utc) + timedelta(hours=2)  # sécurité : revoquer jusqu'à exp probable

    await db.execute(
        text("SELECT logout_user(CAST(:uid AS UUID), :jti, :exp, CAST(:ip AS INET))"),
        {"uid": current_user["user_id"], "jti": jti, "exp": exp, "ip": ip},
    )
    await db.commit()
    return {"message": "Déconnexion réussie"}


@router.post("/refresh", summary="Renouveler le token d'accès")
async def refresh_token(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    payload = _decode_token(body.refresh_token)

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Token de rafraîchissement invalide")

    jti = payload.get("jti", "")
    if await _is_revoked(jti, db):
        raise HTTPException(status_code=401, detail="Token révoqué")

    token_data = {
        "sub":   payload["sub"],
        "email": payload["email"],
        "role":  payload["role"],
    }

    # Récupérer les infos à jour depuis la DB
    result = await db.execute(
        text("""
            SELECT u.first_name, u.last_name, r.role_code, r.role_label
            FROM app_user u JOIN user_role r ON r.role_id = u.role_id
            WHERE u.user_id = :uid AND u.is_active = TRUE
        """),
        {"uid": payload["sub"]},
    )
    user_row = result.mappings().one_or_none()
    if not user_row:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable ou inactif")

    token_data.update({
        "first_name": user_row["first_name"],
        "last_name":  user_row["last_name"],
        "role_label": user_row["role_label"],
    })

    new_access = _create_token(
        token_data,
        timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
        "access",
    )
    return {"access_token": new_access, "token_type": "bearer",
            "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60}


@router.get("/me", response_model=UserInfo, summary="Profil utilisateur connecté")
async def get_me(current_user: CurrentUser):
    return UserInfo(
        user_id=current_user["user_id"],
        email=current_user["email"],
        first_name=current_user["first_name"],
        last_name=current_user["last_name"],
        full_name=f"{current_user['first_name']} {current_user['last_name']}",
        role_code=current_user["role_code"],
        role_label=current_user["role_label"],
        permissions=current_user["permissions"],
    )
