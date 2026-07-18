content = open('/opt/smb-algo-analytics/analytics.html').read()
changes = 0

# 1. Add Trade Lists to SCREENERS
old1 = '{id:"trap", name:"Writers Trap", desc:"Call and Put writers trap signals"}'
new1 = '''{id:"trap", name:"Writers Trap", desc:"Call and Put writers trap signals"},
  {id:"tradelist", name:"Trade Lists", desc:"Combined analytics list for tomorrow's trading"}'''
if old1 in content:
    content = content.replace(old1, new1)
    changes += 1
    print('1. Trade Lists added to screeners')
else:
    print('1. NOT FOUND')

# 2. Add TradeList component before App function
trade_list_component = '''
function TradeList({onBack}) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const [tab, setTab] = React.useState("bullish");
  const [selected, setSelected] = React.useState({});  // {ticker: {direction, sources, account_ids: Set}}

  const run = React.useCallback(async () => {
    setLoading(true);
    const d = await api("/api/analytics/trade_lists/combined");
    setLoading(false);
    if (d && d.status === "ok") {
      setData(d);
      // Initialize selected from already approved
      const sel = {};
      [...d.bullish, ...d.bearish].forEach(s => {
        if (s.approved) {
          sel[s.ticker] = {
            direction: s.direction,
            sources: s.sources,
            account_ids: new Set((s.account_ids||"").split(",").filter(Boolean).map(Number))
          };
        }
      });
      setSelected(sel);
    }
  }, []);

  React.useEffect(() => { run(); }, []);

  const stocks = data ? (tab === "bullish" ? data.bullish : data.bearish) : [];
  const accounts = data ? data.accounts : [];

  const toggleStock = (ticker, direction, sources) => {
    setSelected(prev => {
      const n = {...prev};
      if (n[ticker]) { delete n[ticker]; }
      else { n[ticker] = {direction, sources, account_ids: new Set()}; }
      return n;
    });
  };

  const toggleAccount = (ticker, direction, sources, accId) => {
    setSelected(prev => {
      const n = {...prev};
      if (!n[ticker]) n[ticker] = {direction, sources, account_ids: new Set()};
      else n[ticker] = {...n[ticker], account_ids: new Set(n[ticker].account_ids)};
      if (n[ticker].account_ids.has(accId)) n[ticker].account_ids.delete(accId);
      else n[ticker].account_ids.add(accId);
      if (n[ticker].account_ids.size === 0) delete n[ticker];
      return n;
    });
  };

  const selectAll = (dir) => {
    const stocks_dir = dir === "bullish" ? data.bullish : data.bearish;
    setSelected(prev => {
      const n = {...prev};
      stocks_dir.forEach(s => {
        n[s.ticker] = {direction: s.direction, sources: s.sources, account_ids: new Set(accounts.map(a=>a.id))};
      });
      return n;
    });
  };

  const approve = async () => {
    setSaving(true);
    const stocks_to_save = Object.entries(selected).map(([ticker, v]) => ({
      ticker, direction: v.direction, sources: v.sources, account_ids: [...v.account_ids]
    }));
    const res = await fetch("/analytics/api/analytics/trade_lists/approve", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({date: data.as_of_date, stocks: stocks_to_save})
    });
    const r = await res.json();
    setSaving(false);
    if (r.status === "ok") { setSaved(true); setTimeout(()=>setSaved(false), 3000); }
  };

  const selCount = Object.keys(selected).length;

  return e("div", null,
    e("div", {style:{background:"var(--surface)",borderBottom:"1px solid var(--border)",padding:"0 24px",display:"flex",gap:4,alignItems:"center"}},
      e("button", {className:"btn btn-ghost", style:{margin:"8px 0"}, onClick:onBack}, "← Analytics"),
      e("span", {style:{color:"var(--text-3)",margin:"0 8px"}}, "|"),
      ["bullish","bearish"].map(t => e("button", {key:t,
        style:{padding:"12px 18px",fontSize:13,fontWeight:500,color:tab===t?"var(--blue)":"var(--text-2)",cursor:"pointer",border:"none",background:"none",
               borderBottom:tab===t?"2px solid var(--blue)":"2px solid transparent",marginBottom:"-1px",fontFamily:"var(--sans)"},
        onClick:()=>setTab(t)
      }, (t==="bullish"?"Bullish":"Bearish") + (data?" ("+data.counts[t]+")":"")))
    ),
    e("div", {className:"page"},
      e("div", {style:{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:16,flexWrap:"wrap",gap:8}},
        e("div", null,
          e("div", {style:{fontSize:18,fontWeight:700}}, "Trade Lists"),
          data && e("div", {style:{fontSize:12,color:"var(--text-2)",fontFamily:"var(--mono)"}},
            "As of: "+data.as_of_date+" | "+selCount+" stocks selected")
        ),
        e("div", {style:{display:"flex",gap:8}},
          e("button", {className:"btn btn-ghost", onClick:()=>selectAll(tab)}, "Select All "+tab),
          e("button", {
            className:"btn btn-blue",
            onClick:approve,
            disabled:saving||selCount===0
          }, saved?"✓ Saved!":saving?"Saving...":"▶ Approve for Tomorrow ("+selCount+")")
        )
      ),
      loading && e("div", {style:{textAlign:"center",padding:40,color:"var(--text-2)"}}, "Loading..."),
      data && e("div", {className:"section-card"},
        e("div", {style:{overflowX:"auto"}},
          e("table", {style:{width:"100%",borderCollapse:"collapse",fontSize:12}},
            e("thead", null, e("tr", null,
              [e("th",{key:"sel",style:{width:36,padding:"8px 10px",borderBottom:"2px solid var(--border)",background:"var(--surface2)"}}, "✓"),
               e("th",{key:"tk",style:{textAlign:"left",padding:"8px 10px",fontSize:10,fontWeight:600,color:"var(--text-2)",textTransform:"uppercase",borderBottom:"2px solid var(--border)",background:"var(--surface2)"}}, "Symbol"),
               e("th",{key:"src",style:{textAlign:"left",padding:"8px 10px",fontSize:10,fontWeight:600,color:"var(--text-2)",textTransform:"uppercase",borderBottom:"2px solid var(--border)",background:"var(--surface2)"}}, "Sources"),
               ...accounts.map(a => e("th",{key:a.id,style:{textAlign:"center",padding:"8px 10px",fontSize:10,fontWeight:600,color:"var(--text-2)",textTransform:"uppercase",borderBottom:"2px solid var(--border)",background:"var(--surface2)"}}, a.name))
              ]
            )),
            e("tbody", null,
              stocks.map(s => {
                const isSel = !!selected[s.ticker];
                const bg = isSel ? (tab==="bullish"?"#edf7ed":"#fef2f2") : "transparent";
                return e("tr", {key:s.ticker, style:{background:bg}},
                  e("td", {style:{textAlign:"center",padding:"9px 10px",borderBottom:"1px solid var(--border)"}},
                    e("input", {type:"checkbox", checked:isSel, onChange:()=>toggleStock(s.ticker, s.direction, s.sources)})
                  ),
                  e("td", {style:{fontWeight:700,padding:"9px 10px",borderBottom:"1px solid var(--border)"}}, s.ticker),
                  e("td", {style:{padding:"9px 10px",borderBottom:"1px solid var(--border)"}},
                    e("span", {className:"list-tag"}, s.sources),
                    s.source_count >= 2 && e("span", {style:{marginLeft:4,fontSize:10,color:"var(--buy)",fontWeight:700}}, "★")
                  ),
                  ...accounts.map(a => e("td", {key:a.id, style:{textAlign:"center",padding:"9px 10px",borderBottom:"1px solid var(--border)"}},
                    e("input", {
                      type:"checkbox",
                      checked: isSel && !!(selected[s.ticker]?.account_ids?.has(a.id)),
                      disabled: !isSel,
                      onChange:()=>toggleAccount(s.ticker, s.direction, s.sources, a.id)
                    })
                  ))
                );
              })
            )
          )
        )
      )
    )
  );
}

'''

old2 = 'function App() {'
new2 = trade_list_component + 'function App() {'
if old2 in content:
    content = content.replace(old2, new2)
    changes += 1
    print('2. TradeList component added')
else:
    print('2. NOT FOUND')

# 3. Wire into router
old3 = ': screener === "poip"\n        ? e(POIPScreener,{onBack:()=>setView("landing")})\n        : e("div",{className:"page"},"Coming soon")'
new3 = ': screener === "poip"\n        ? e(POIPScreener,{onBack:()=>setView("landing")})\n        : screener === "tradelist"\n        ? e(TradeList,{onBack:()=>setView("landing")})\n        : e("div",{className:"page"},"Coming soon")'
if old3 in content:
    content = content.replace(old3, new3)
    changes += 1
    print('3. Wired into router')
else:
    print('3. Router NOT FOUND')

open('/opt/smb-algo-analytics/analytics.html', 'w').write(content)
print(f'Total changes: {changes}/3')
