content = open('/opt/smb-algo-analytics/analytics.html').read()
changes = 0

# 1. Enable POIP screener
old = '{id:"poip", name:"POIP Screener", desc:"Price and OI percentile breakout signals", disabled:true}'
new = '{id:"poip", name:"POIP Screener", desc:"Price and OI percentile breakout signals"}'
if old in content:
    content = content.replace(old, new)
    changes += 1
    print('1. POIP enabled')
else:
    print('1. POIP NOT FOUND')

# 2. Remove C-OI% from OI Buildup headers
old2 = '["Symbol","Sector","Inst","Lists","C1","C2","HC","Futures","IVP","PP%","OI%","POIP",isBull?"CWT":"PWT","HCSP","C-OI%","C-Diff%","HPSP","P-OI%","P-Diff%","PCR-OI","Score"]'
new2 = '["Symbol","Sector","Inst","Lists","C1","C2","HC","Futures","IVP","PP%","OI%","POIP",isBull?"CWT":"PWT","HCSP","C-Diff%","HPSP","P-Diff%","PCR-OI","Score"]'
if old2 in content:
    content = content.replace(old2, new2)
    changes += 1
    print('2. OI Buildup headers fixed')
else:
    print('2. OI Buildup headers NOT FOUND')

# 3. Remove call_chg_oi column from OI Buildup rows
old3 = 'e("td",{className:"td-mono"},s.call_chg_oi!=null?fmtNum(s.call_chg_oi,1)+"%":"—"),\n                      e("td",{className:"td-mono"},s.call_diff'
new3 = 'e("td",{className:"td-mono"},s.call_diff'
if old3 in content:
    content = content.replace(old3, new3)
    changes += 1
    print('3. OI Buildup call_chg_oi removed')
else:
    print('3. OI Buildup call_chg_oi NOT FOUND')

# 4. Remove put_chg_oi column from OI Buildup rows
old4 = 'e("td",{className:"td-mono"},s.put_chg_oi!=null?fmtNum(s.put_chg_oi,1)+"%":"—"),\n                      e("td",{className:"td-mono"},s.put_diff'
new4 = 'e("td",{className:"td-mono"},s.put_diff'
if old4 in content:
    content = content.replace(old4, new4)
    changes += 1
    print('4. OI Buildup put_chg_oi removed')
else:
    print('4. OI Buildup put_chg_oi NOT FOUND')

# 5. Remove C-OI% from Writers Trap headers
old5 = '["Symbol","Sector","Inst","Cycle","C1","C2","Ret%","Futures","IVP","PP%","OI%","POIP","HCSP","C-OI%","C-Diff%","HPSP","P-OI%","P-Diff%","Score"]'
new5 = '["Symbol","Sector","Inst","Cycle","C1","C2","Ret%","Futures","IVP","PP%","OI%","POIP","HCSP","C-Diff%","HPSP","P-Diff%","Score"]'
if old5 in content:
    content = content.replace(old5, new5)
    changes += 1
    print('5. Trap headers fixed')
else:
    print('5. Trap headers NOT FOUND')

# 6. Remove call_chg_oi from Trap rows
old6 = 'e("td",{style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.call_chg_oi!=null?s.call_chg_oi.toFixed(1)+"%":"—"),\n                      e("td",{style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.call_diff'
new6 = 'e("td",{style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.call_diff'
if old6 in content:
    content = content.replace(old6, new6)
    changes += 1
    print('6. Trap call_chg_oi removed')
else:
    print('6. Trap call_chg_oi NOT FOUND')

# 7. Remove put_chg_oi from Trap rows
old7 = 'e("td",{style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.put_chg_oi!=null?s.put_chg_oi.toFixed(1)+"%":"—"),\n                      e("td",{style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.put_diff'
new7 = 'e("td",{style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.put_diff'
if old7 in content:
    content = content.replace(old7, new7)
    changes += 1
    print('7. Trap put_chg_oi removed')
else:
    print('7. Trap put_chg_oi NOT FOUND')

# 8. Add POIP component before App function and wire into router
poip_component = '''
function POIPScreener({onBack}) {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [tab, setTab] = React.useState("bullish");

  const run = React.useCallback(async () => {
    setLoading(true);
    const d = await api("/api/analytics/poip");
    setLoading(false);
    if (d && d.status === "ok") setData(d);
  }, []);

  React.useEffect(() => { run(); }, []);

  const stocks = data ? (tab === "bullish" ? data.bullish : data.bearish) : [];
  const isBull = tab === "bullish";
  const hdrs = ["Symbol","Sector","Inst","Cycle","C1","C2","PP%","OI%","OIP 20d","Futures","IVP","HCSP","C-Diff%","HPSP","P-Diff%","Trap","Score"];

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
      e("div", {style:{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:16}},
        e("div", null,
          e("div", {style:{fontSize:18,fontWeight:700}}, "POIP Screener"),
          data && e("div", {style:{fontSize:12,color:"var(--text-2)",fontFamily:"var(--mono)"}}, "As of: "+data.as_of_date+" | PP>"+(isBull?"90":"10")+" & OI%>90 + L:LU/S:SC cycle")
        ),
        e("button", {className:"btn btn-blue", onClick:run, disabled:loading}, loading?"Running...":"▶ Run Again")
      ),
      loading && e("div", {style:{textAlign:"center",padding:40,color:"var(--text-2)"}}, "Running screener..."),
      data && e("div", {className:"section-card"},
        stocks.length === 0
          ? e("div", {style:{textAlign:"center",padding:20,color:"var(--text-3)"}}, "No "+tab+" signals today")
          : e("div", {style:{overflowX:"auto"}},
              e("table", {style:{width:"100%",borderCollapse:"collapse",fontSize:12}},
                e("thead", null, e("tr", null,
                  hdrs.map(h => e("th", {key:h, style:{textAlign:"left",padding:"8px 10px",fontSize:10,fontWeight:600,color:"var(--text-2)",textTransform:"uppercase",letterSpacing:"0.07em",borderBottom:"2px solid var(--border)",whiteSpace:"nowrap",background:"var(--surface2)"}}, h))
                )),
                e("tbody", null,
                  stocks.map(s => {
                    const bg = s.score>=3?"#d4edda":s.score===2?"#e8f5e9":s.score===1?"#fff8e1":"transparent";
                    return e("tr", {key:s.ticker, style:{background:bg}},
                      e("td", {style:{fontWeight:700,padding:"9px 10px",borderBottom:"1px solid var(--border)",whiteSpace:"nowrap"}}, s.ticker),
                      e("td", {style:{fontSize:11,padding:"9px 10px",borderBottom:"1px solid var(--border)"}}, s.sector),
                      e("td", {style:{padding:"9px 10px",borderBottom:"1px solid var(--border)"}},
                        e("span", {style:{fontSize:10,padding:"2px 6px",borderRadius:4,background:s.instrument==="Options"?"var(--buy-bg)":"var(--surface2)",color:s.instrument==="Options"?"var(--buy)":"var(--text-2)",border:"1px solid "+(s.instrument==="Options"?"var(--buy-bd)":"var(--border)"),fontWeight:600}}, s.instrument)
                      ),
                      e("td", {style:{padding:"9px 10px",borderBottom:"1px solid var(--border)"}},
                        s.in_cycle ? e("span", {style:{color:"var(--buy)",fontWeight:700}}, "✓") : e("span", {style:{color:"var(--text-3)"}}, "—")
                      ),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.c1_score),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.c2_score),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11,fontWeight:600,color:"var(--buy)"}}, s.pp!=null?s.pp.toFixed(1):"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11,fontWeight:600,color:"var(--buy)"}}, s.oip!=null?s.oip.toFixed(1):"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.oip_avg_20!=null?s.oip_avg_20.toFixed(1):"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.futures?s.futures.toFixed(1):"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.ivp!=null?s.ivp.toFixed(1):"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.call_strike||"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.call_diff!=null?s.call_diff.toFixed(2)+"%":"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.put_strike||"—"),
                      e("td", {style:{fontFamily:"var(--mono)",padding:"9px 10px",borderBottom:"1px solid var(--border)",fontSize:11}}, s.put_diff!=null?s.put_diff.toFixed(2)+"%":"—"),
                      e("td", {style:{padding:"9px 10px",borderBottom:"1px solid var(--border)",color:s.trap?"var(--buy)":"var(--text-3)",fontWeight:s.trap?700:400}}, s.trap?"✓":"—"),
                      e("td", {style:{padding:"9px 10px",borderBottom:"1px solid var(--border)",fontWeight:700,color:s.score>=2?"var(--buy)":s.score===1?"#b45309":"var(--text-2)"}}, s.score)
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

old8 = 'function App() {'
new8 = poip_component + 'function App() {'
if old8 in content:
    content = content.replace(old8, new8)
    changes += 1
    print('8. POIP component added')
else:
    print('8. App function NOT FOUND')

# 9. Wire POIP into App router
old9 = ': screener === "trap"\n        ? e(WritersTrap,{onBack:()=>setView("landing")})\n        : e("div",{className:"page"},"Coming soon")'
new9 = ': screener === "trap"\n        ? e(WritersTrap,{onBack:()=>setView("landing")})\n        : screener === "poip"\n        ? e(POIPScreener,{onBack:()=>setView("landing")})\n        : e("div",{className:"page"},"Coming soon")'
if old9 in content:
    content = content.replace(old9, new9)
    changes += 1
    print('9. POIP wired into router')
else:
    print('9. Router NOT FOUND')

open('/opt/smb-algo-analytics/analytics.html', 'w').write(content)
print(f'\nTotal changes: {changes}/9')
