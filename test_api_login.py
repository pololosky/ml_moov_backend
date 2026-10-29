import urllib.request, json

CREDS = [
    ("admin@moov-africa.tg",      "Admin$Root2024!"),
    ("marketing@moov-africa.tg",  "Marketing2024!"),
    ("data@moov-africa.tg",       "DataPipeline#Secure99"),
]

for email, password in CREDS:
    data = json.dumps({"email": email, "password": password}).encode()
    req = urllib.request.Request(
        "http://localhost:8000/api/auth/login",
        data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=6) as r:
            b = json.loads(r.read().decode())
            u = b.get("user", {})
            print(f"OK  {email} | role={u.get('role_code')} | {len(u.get('permissions',[]))} perms")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body[:200]
        print(f"FAIL {email} [{e.code}]: {detail}")
