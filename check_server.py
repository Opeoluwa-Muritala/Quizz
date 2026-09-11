import urllib.request

routes = ["/", "/jobs", "/apply", "/login", "/admin", "/admin/recruitment", "/admin/jobs"]
for r in routes:
    try:
        url = "http://127.0.0.1:5000" + r
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            print(f"{r} -> HTTP {resp.status} (Length: {len(content)})")
    except urllib.error.HTTPError as e:
        print(f"{r} -> HTTP {e.code}")
    except Exception as e:
        print(f"{r} -> ERROR: {e}")
