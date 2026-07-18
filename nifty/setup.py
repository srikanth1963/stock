import os

files = {}

files['__init__.py'] = '"""SMB Algo Platform"""'
files['core/__init__.py'] = '"""SMB Algo — Core package"""'
files['webhooks/__init__.py'] = ''
files['auth/__init__.py'] = ''
files['api/__init__.py'] = ''
files['strategies/__init__.py'] = ''
files['strategies/utlrg/__init__.py'] = ''
files['scripts/__init__.py'] = ''

for path, content in files.items():
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else '.', exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)
    print(f'✓ {path}')

print('Done!')
