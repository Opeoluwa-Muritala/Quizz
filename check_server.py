import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:5000/") as resp:
        content = resp.read().decode("utf-8")
        print("STATUS:", resp.status)
        for i, line in enumerate(content.splitlines()[:60]):
            print(f"{i+1:02d}: {line}")
except Exception as e:
    print("ERROR:", e)
