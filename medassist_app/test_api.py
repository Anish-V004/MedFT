import urllib.request
import urllib.error
import urllib.parse
import http.cookiejar
import json
import re

JUPYTER_TOKEN = "1a09c93ecf61524f6b92fa1ee74a7d543f6e753da18b825b"
VLLM_API_KEY  = "anish123"
BASE_URL      = "https://notebooks.amd.com/jupyter-hack-team-2564-260616170419-201b784b"
PROXY_BASE    = BASE_URL + "/proxy/8000"

# ── Step 1: Login to Jupyter to get a session cookie ─────────────────────────
cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

login_url = BASE_URL + "/login"

# GET login page to extract XSRF token
login_page = opener.open(login_url).read().decode()
xsrf_match = re.search(r'name="_xsrf"\s+value="([^"]+)"', login_page)
xsrf = xsrf_match.group(1) if xsrf_match else ""
print(f"XSRF: {xsrf[:20]}..." if xsrf else "XSRF: NOT FOUND")

# POST login
login_data = urllib.parse.urlencode({"password": JUPYTER_TOKEN, "_xsrf": xsrf}).encode()
login_req = urllib.request.Request(
    login_url,
    data=login_data,
    method="POST",
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)
try:
    resp = opener.open(login_req)
    print(f"Login: OK (status {resp.status})")
except urllib.error.HTTPError as e:
    print(f"Login HTTP error: {e.code}")
except Exception as e:
    print(f"Login error: {e}")

# ── Step 2: GET /v1/models ────────────────────────────────────────────────────
print("\n=== GET /v1/models ===")
req = urllib.request.Request(
    PROXY_BASE + "/v1/models",
    headers={"Authorization": "Bearer " + VLLM_API_KEY},
)
try:
    with opener.open(req, timeout=15) as r:
        body = r.read().decode()
        print(f"Status: {r.status}")
        try:
            print(json.dumps(json.loads(body), indent=2))
        except Exception:
            print(body[:500])
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    print(e.read().decode()[:300])
except Exception as e:
    print(f"Error: {e}")

# ── Step 3: Quick chat completion test ───────────────────────────────────────
print("\n=== POST /v1/chat/completions ===")
payload = json.dumps({
    "model": "medft",
    "messages": [{"role": "user", "content": "Hello, what model are you?"}],
    "max_tokens": 30,
    "temperature": 0.1,
}).encode()

req2 = urllib.request.Request(
    PROXY_BASE + "/v1/chat/completions",
    data=payload,
    method="POST",
    headers={
        "Authorization": "Bearer " + VLLM_API_KEY,
        "Content-Type": "application/json",
    },
)
try:
    with opener.open(req2, timeout=60) as r:
        body = r.read().decode()
        print(f"Status: {r.status}")
        try:
            data = json.loads(body)
            print(json.dumps(data, indent=2))
        except Exception:
            print(body[:600])
except urllib.error.HTTPError as e:
    print(f"HTTP Error: {e.code}")
    print(e.read().decode()[:400])
except Exception as e:
    print(f"Error: {e}")
