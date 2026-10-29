"""Script one-shot : corrige la fonction authenticate_user en base."""
import psycopg2, os

DB = os.getenv(
    "SYNC_DATABASE_URL",
    "postgresql://postgres:19082005@localhost:5432/moov_africa_db_test"
).replace("postgresql+psycopg2://", "postgresql://")

conn = psycopg2.connect(DB)
conn.autocommit = True
cur = conn.cursor()

# Supprimer l'ancienne version d'abord (type de retour différent)
cur.execute("DROP FUNCTION IF EXISTS authenticate_user(VARCHAR, VARCHAR, INET, VARCHAR)")
print("✓ Ancienne fonction supprimée")

with open("fix_authenticate_user.sql", encoding="utf-8") as f:
    sql = f.read()

cur.execute(sql)
print("✓ Fonction authenticate_user corrigée")

# Test
cur.execute(
    "SELECT out_user_id, out_email, out_role_code "
    "FROM authenticate_user(%s, %s, %s::INET, %s)",
    ("admin@moov-africa.tg", "Admin$Root2024!", "127.0.0.1", "test"),
)
row = cur.fetchone()
if row:
    print(f"✓ Login OK — user_id={row[0]}, email={row[1]}, role={row[2]}")
else:
    print("✗ Login retourne NULL (mauvais mdp ou compte inactif)")

cur.close()
conn.close()
