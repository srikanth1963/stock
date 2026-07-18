"""
Patch to add pull_analytics() to gsheet_pull.py
Creates analytics_config table and pulls Analytics GSheet tab
"""
import subprocess

content = open('/opt/smb-algo-stocks/gsheet_pull.py').read()

# Add pull_analytics function before def main()
new_func = '''
def pull_analytics(mc):
    print("Pulling Analytics config...")
    rows = fetch_tab("Analytics")
    if not rows or len(rows) < 17:
        print("  Analytics tab missing or incomplete")
        return
    try:
        mc.execute("""CREATE TABLE IF NOT EXISTS analytics_config (
            key TEXT PRIMARY KEY,
            value REAL,
            description TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )""")
        mc.commit()

        # Fixed row positions (0-indexed)
        mapping = [
            (2,  'cycle1_days',   'Cycle 1 lookback days'),
            (3,  'cycle1_llu',    'Cycle 1 L:LU threshold (Bullish)'),
            (4,  'cycle1_ssc',    'Cycle 1 S:SC threshold (Bearish)'),
            (5,  'cycle2_days',   'Cycle 2 lookback days'),
            (6,  'cycle2_llu',    'Cycle 2 L:LU threshold (Bullish)'),
            (7,  'cycle2_ssc',    'Cycle 2 S:SC threshold (Bearish)'),
            (8,  'pp_bearish',    'Price Percentile less than (Bearish)'),
            (9,  'pp_bullish',    'Price Percentile more than (Bullish)'),
            (10, 'oi_pct',        'OI Percentile more than (Both)'),
            (11, 'ivp_writing',   'IVP greater than (Writing)'),
            (12, 'ivp_long',      'IVP less than (Long)'),
            (13, 'ivhv_writing',  'IV-HV greater than (Writing)'),
            (14, 'ivhv_long',     'IV-HV less than (Long/Risky)'),
            (15, 'pcr_bearish',   'PCR Percentile above (Bearish reversal)'),
            (16, 'pcr_bullish',   'PCR Percentile below (Bullish reversal)'),
        ]

        count = 0
        for row_idx, key, desc in mapping:
            if row_idx < len(rows) and len(rows[row_idx]) > 1:
                val_str = rows[row_idx][1].strip()
                if val_str:
                    try:
                        val = float(val_str)
                        mc.execute(
                            "INSERT OR REPLACE INTO analytics_config (key, value, description, updated_at) VALUES (?, ?, ?, datetime('now'))",
                            (key, val, desc)
                        )
                        count += 1
                    except ValueError:
                        pass

        mc.commit()
        print(f"  {count} analytics parameters loaded")
    except Exception as e:
        print(f"  Analytics pull error: {e}")

'''

old_main = 'def main():'
if old_main in content:
    content = content.replace(old_main, new_func + 'def main():')
    print('Function added')
else:
    print('NOT FOUND - main()')

# Add pull_analytics(mc) call in main()
old_call = '        pull_sector_stock(mc); pull_index_stock(mc)'
new_call = '        pull_sector_stock(mc); pull_index_stock(mc)\n        pull_analytics(mc)'
if old_call in content:
    content = content.replace(old_call, new_call)
    print('Call added to main()')
else:
    print('NOT FOUND - main() call')

open('/opt/smb-algo-stocks/gsheet_pull.py', 'w').write(content)

# Verify syntax
result = subprocess.run(['python3', '-m', 'py_compile', '/opt/smb-algo-stocks/gsheet_pull.py'], capture_output=True)
if result.returncode == 0:
    print('Syntax OK')
else:
    print('Syntax ERROR:', result.stderr.decode())
