content = open('/opt/smb-algo-stocks/index.html').read()

old = """        e(PnLBar, {
          realised: accData.realised_pnl,
          unrealised: accData.unrealised_pnl,
          limit: accData.max_daily_loss
        }),"""

new = """        e('div', {className:'pnl-bar-wrap'},
          e('div', {className:'pnl-bar-track'},
            e('div', {
              className:'pnl-bar-fill ' + ((accData.total_deployed||0)/(accData.capital||1)*100 > 90 ? 'danger' : (accData.total_deployed||0)/(accData.capital||1)*100 > 70 ? 'warn' : ''),
              style:{width: Math.min(100,(accData.total_deployed||0)/(accData.capital||1)*100) + '%'}
            })
          ),
          e('div', {className:'pnl-bar-labels'},
            e('span', null, 'Deployed: \u20b9' + (accData.total_deployed||0).toLocaleString('en-IN')),
            e('span', null, 'Capital: \u20b9' + (accData.capital||0).toLocaleString('en-IN') + ' (90% = \u20b9' + ((accData.capital||0)*0.9).toLocaleString('en-IN') + ')')
          )
        ),
        e(PnLBar, {
          realised: accData.realised_pnl,
          unrealised: accData.unrealised_pnl,
          limit: accData.max_daily_loss
        }),"""

if old in content:
    open('/opt/smb-algo-stocks/index.html', 'w').write(content.replace(old, new))
    print('Fixed')
else:
    print('NOT FOUND')
