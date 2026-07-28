import psycopg2

conn = psycopg2.connect("postgresql://postgres:19082005@localhost:5432/moov_africa_db_test")
conn.autocommit = True
cur = conn.cursor()

cur.execute(
    "SELECT * FROM authenticate_user(%s, %s, %s::INET, %s)",
    ("admin@moov-africa.tg", "Admin$Root2024!", "127.0.0.1", "test"),
)
row = cur.fetchone()
cols = [d[0] for d in cur.description]
print("Colonnes:", cols)
print("Valeurs :", row)

# Test aussi avec email invalide
cur.execute(
    "SELECT * FROM authenticate_user(%s, %s, %s::INET, %s)",
    ("admin@moov-africa.tg", "mauvais_mdp", "127.0.0.1", "test"),
)
row2 = cur.fetchone()
print("Mauvais mdp:", row2)

conn.close()
