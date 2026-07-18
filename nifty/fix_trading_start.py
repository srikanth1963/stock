import ast, sys

path = '/opt/smb-algo/webhooks/utlrg.py'
content = open(path).read()

old = 'TRADING_START = time(9, 20, 30)   # 9:20:30 AM IST'
new = 'TRADING_START = time(9, 20)   # 9:20 AM IST — matches morning scheduler'

if old not in content:
    print("ERROR: pattern not found")
    sys.exit(1)

content = content.replace(old, new, 1)

try:
    ast.parse(content)
except SyntaxError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)

open(path, 'w').write(content)
print("TRADING_START fixed to time(9, 20)")
