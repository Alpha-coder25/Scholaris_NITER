"""Lightweight DAST probe — headers, XSS/SQLi reflection, auth bypass.

Usage:  python dast_probe.py [base_url]
Default base: http://localhost:8000
Prints a PASS/FAIL line per check; exits nonzero if any check fails.
"""
import re
import sys

import requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
TIMEOUT = 15

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


# ---------------------------------------------------------------------------
# 1. Security headers on the landing page
# ---------------------------------------------------------------------------
r = requests.get(BASE + "/", timeout=TIMEOUT, allow_redirects=True)
h = {k.lower(): v for k, v in r.headers.items()}
check("landing page returns 200", r.status_code == 200, f"status={r.status_code}")
check("X-Content-Type-Options: nosniff", h.get("x-content-type-options", "").lower() == "nosniff")
check("X-Frame-Options present", "x-frame-options" in h, h.get("x-frame-options", "(missing)"))
check("Referrer-Policy present", "referrer-policy" in h, h.get("referrer-policy", "(missing)"))
check("HSTS present on HTTPS", ("strict-transport-security" in h) if BASE.startswith("https") else True)
check("server header not leaking", "server" not in h or "django" not in h.get("server", "").lower(),
      h.get("server", "(none)"))

# ---------------------------------------------------------------------------
# 2. Reflected XSS probes — payload must be escaped, not echoed raw
# ---------------------------------------------------------------------------
xss_payload = '<script>alert(1)</script>'
r = requests.get(BASE + "/?q=" + xss_payload, timeout=TIMEOUT)
check("reflected XSS not executed raw", r.status_code < 500 and xss_payload not in r.text,
      "payload echoed raw" if xss_payload in r.text else "escaped/absent")

xss_payload2 = '"><svg onload=alert(1)>'
r = requests.get(BASE + "/?q=" + xss_payload2, timeout=TIMEOUT)
check("XSS variant 2 not reflected raw", xss_payload2 not in r.text)

# ---------------------------------------------------------------------------
# 3. SQL injection probes — no 500s, no DB error strings leaked
# ---------------------------------------------------------------------------
sqli_probes = [
    "' OR '1'='1",
    "'; DROP TABLE users; --",
    "1' UNION SELECT username,password FROM auth_user--",
    "' OR 1=1 --",
    "1 AND SLEEP(5)",
]
leak_patterns = [
    r"sqlite3\.OperationalError",
    r"django\.db",
    r"UNIQUE constraint failed",
    r"psycopg",
    r"syntax error",
]
for i, p in enumerate(sqli_probes):
    r = requests.get(BASE + "/?q=" + p, timeout=TIMEOUT)
    leaked = any(re.search(pat, r.text, re.IGNORECASE) for pat in leak_patterns)
    check(f"SQLi probe {i + 1} clean", r.status_code < 500 and not leaked,
          f"status={r.status_code}" + (" DB error leaked!" if leaked else ""))

# ---------------------------------------------------------------------------
# 4. Auth bypass — protected routes must NOT return 200 anonymously
# ---------------------------------------------------------------------------
protected = [
    "/admin/dashboard/", "/teacher/dashboard/", "/student/dashboard/",
    "/exams/",
]
for path in protected:
    r = requests.get(BASE + path, timeout=TIMEOUT, allow_redirects=False)
    check(f"auth: {path} not 200 anonymous", r.status_code != 200, f"status={r.status_code}")

# ---------------------------------------------------------------------------
# 5. HTTP method enforcement
# ---------------------------------------------------------------------------
for path in ["/", "/accounts/login/"]:
    r = requests.post(BASE + path, timeout=TIMEOUT, allow_redirects=False)
    check(f"method: POST {path} not 500", r.status_code < 500, f"status={r.status_code}")

# ---------------------------------------------------------------------------
# 6. Cookie flags after a real login (demo account)
# ---------------------------------------------------------------------------
s = requests.Session()
r = s.get(BASE + "/accounts/login/?demo=admin", timeout=TIMEOUT, allow_redirects=True)
session_cookie = next(
    (c for c in s.cookies if c.name == "sessionid"), None
)
check("session cookie set after login", session_cookie is not None, "(none)")
if session_cookie is not None:
    check("session cookie HttpOnly", session_cookie.has_nonstandard_attr("HttpOnly")
          or "httponly" in str(session_cookie._rest).lower())
    samesite = str(session_cookie._rest.get("SameSite", "")).lower()
    check("session cookie SameSite", samesite in ("lax", "strict"), samesite or "(unset)")
    if BASE.startswith("https"):
        check("session cookie Secure on HTTPS", session_cookie.secure)

# ---------------------------------------------------------------------------
# 7. Login CSRF token present
# ---------------------------------------------------------------------------
r = requests.get(BASE + "/accounts/login/", timeout=TIMEOUT)
check("login page serves 200", r.status_code == 200, f"status={r.status_code}")
check("csrf token present in form", "csrfmiddlewaretoken" in r.text)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)}/{len(results)} DAST checks passed")
if failed:
    print("Failed:", failed)
sys.exit(1 if failed else 0)
