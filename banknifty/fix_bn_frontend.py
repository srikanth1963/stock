import sys

path = '/opt/smb-algo-bn/frontend/index.html'
content = open(path).read()

replacements = [
    (
        "const API = window.location.origin;",
        "const API = window.location.origin + '/banknifty';"
    ),
    (
        "fetch('/api/settings/lot-size',",
        "fetch(API+'/api/settings/lot-size',"
    ),
    (
        "fetch('/api/settings/trading-mode',",
        "fetch(API+'/api/settings/trading-mode',"
    ),
    (
        "window.open('/auth/breeze/login/Primary','_blank','width=480,height=620')",
        "window.open(API+'/auth/breeze/login/Primary','_blank','width=480,height=620')"
    ),
    (
        "window.open(`/auth/breeze/login/${name}`,'_blank','width=480,height=620')",
        "window.open(API+`/auth/breeze/login/${name}`,'_blank','width=480,height=620')"
    ),
]

for old, new in replacements:
    count = content.count(old)
    if count != 1:
        print(f"ERROR: expected 1 match, found {count} for: {old[:60]}...")
        sys.exit(1)
    content = content.replace(old, new, 1)

open(path, 'w').write(content)
print("All 5 replacements applied successfully")
