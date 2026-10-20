// Control Room view. Every number comes from this server's REST/WS API for the current paper run.
// Rules (enforced by tests/test_ui_real_data.py): no random numbers, no timers that invent data, no CDNs.
// Anything the API does not provide is rendered as NO DATA.
let CRCH=[],CRWS=null,CRTF=900,CRSYM='BTCUSDT';
const ND='<span class="nd">NO DATA</span>';
const crv=(v,f)=>v===null||v===undefined||v===''?ND:(f?f(v):esc(v));
const crSign=v=>{const x=+v;return isNaN(x)?'':x>0?'pos':x<0?'neg':''};
function crBox(k,v,cls=''){return `<div class="crbox"><div class="crk">${k}</div><div class="crv ${cls}">${v}</div></div>`}
function crPanel(t,body,id=''){return `<div class="crp" ${id?`id="${id}"`:''}><div class="crt">${t}</div>${body}</div>`}
async function controlRoom(P){
  CRCH.forEach(c=>{try{c.remove()}catch{}});CRCH=[];if(CRWS){try{CRWS.close()}catch{};CRWS=null}
  const [pnl,pipe,risk,mk,audit]=await Promise.all([api('pnl'),api('pipeline'),api('risk'),api('markets'),api('audit')]);
  const p=pnl.paper,st=Object.fromEntries(pipe.stages.map(s=>[s.stage,s])),lastFill=mk.fills.length?mk.fills[mk.fills.length-1]:null;
  const dec=pipe.last_decision;
  P.innerHTML=`<section class="w3 cr">
  <div class="crhead"><span class="crtitle">GROK TRADING CREW + JEV</span><span class="crbadge">PAPER ONLY</span><span class="crbadge r">LIVE ORDERS DISABLED</span>
   <span class="dim">mode ${esc(S.mode)} · run ${esc((pipe.run_id||'').slice(0,8))||'NO DATA'} · data: ${esc(mk.label)}</span><span id="crclock" class="crclock"></span></div>
  <div class="crticker">
   ${crBox('CHIEF · MAIN GROK',dec?esc(dec.content.replace(/^rationale: /,'')):ND)}
   ${crBox('SCAN',crv(st.SCAN&&st.SCAN.detail))}
   ${crBox('VET · RISK VETOES',crv(S.vetoes),+S.vetoes?'neg':'pos')}
   ${crBox('SIZE · LAST FILL',lastFill?`${esc(lastFill.side)} ${esc(lastFill.qty)} ${esc(lastFill.symbol)} @ ${esc(lastFill.px)}`:ND)}
   ${crBox('FILLS',crv(S.fills))}
   ${crBox('RISK · KILL',risk.kill.engaged?'ENGAGED: '+esc(risk.kill.reason):'ARMED',risk.kill.engaged?'neg':'warnc')}
   ${crBox('NET PNL AFTER COSTS',crv(p.net_pnl_after_costs),crSign(p.net_pnl_after_costs))}
   ${crBox('RECON DRIFT',crv(p.reconciliation_drift))}
  </div>
  <div class="crgrid">
   <div class="crcol">
    ${crPanel('PRICE <select id="crsym"></select> <span id="crtf"></span>','<div id="crpx" class="crchart"></div><small id="crpxl" class="dim"></small>')}
    ${crPanel('DEPTH / ORDER BOOK','<div id="crbook">'+ND+'</div>')}
    ${crPanel('PIPELINE · REAL STAGE STATUS (this run)',`<table class="crtab">${pipe.stages.map(s=>`<tr><td>${s.stage}</td><td class="dim">${esc(s.agent)}</td><td class="${{OK:'pos',ARMED:'warnc',VETO:'warnc','NO DATA':'dim'}[s.status]||'neg'}">${esc(s.status)}</td><td>${esc(s.detail)}</td></tr>`).join('')}</table>`)}
   </div>
   <div class="crcol">
    ${crPanel('CANDLES · '+esc(CRSYM),'<div id="crcd" class="crchart tall"></div>')}
    ${crPanel('BALANCE · PAPER EQUITY (mark-to-market)',`<div class="crbig ${crSign(p.net_pnl_after_costs)}">${crv(p.final_equity_mtm)} <span class="crsub">USDT</span></div>
      <div class="dim">start ${crv(p.start_equity)} · net ${crv(p.net_pnl_after_costs)} · fees ${crv(p.fees_paid)} · fills ${crv(S.fills)} · drift ${crv(p.reconciliation_drift)}</div><div id="creq" class="crchart"></div>`)}
   </div>
   <div class="crcol">
    ${crPanel('THRESHOLDS · HASH-LOCKED (read-only)',`<div class="dim">sha256 ${esc(risk.limits_sha256.slice(0,16))}… · file ok: <span class="${risk.limits_file_ok?'pos':'neg'}">${risk.limits_file_ok}</span></div><table class="crtab">${Object.entries(risk.limits).map(([k,v])=>`<tr><td>${esc(k)}</td><td class="warnc">${esc(v)}</td></tr>`).join('')}</table>`)}
    ${crPanel('JUDGE LOG · audit + vetoes + live trace feed','<div id="crj" class="crlog"></div><small id="crjs" class="dim">trace feed: connecting…</small>')}
   </div>
  </div></section>`;
  const clk=$('#crclock'),gc=$('#clock');if(clk&&gc)clk.textContent=gc.textContent;   // mirrors the footer IST clock
  // judge log: real audit rows + real vetoes/risk events, then append real trace rows from the WS feed
  const J=[];audit.slice(-20).forEach(a=>J.push(`<div><span class="dim">${esc(a[1])}</span> AUDIT ${esc(a[2])} ${esc(a[3])} ${esc(a[4])}</div>`));
  risk.risk_events.slice(-20).forEach(e=>J.push(`<div class="${e[2]=='KILL'?'neg':'warnc'}">${esc(e[2])} ${esc(e[4])}</div>`));
  mk.vetoes.slice(-20).forEach(v=>J.push(`<div class="warnc">VETO ${esc(v.symbol)} ${esc(v.reasons.join('; '))}</div>`));
  const jl=$('#crj');jl.innerHTML=J.join('')||'<div class="dim">no audit rows, vetoes or risk events in this run</div>';
  crFeed();await crPrice();await crBook();crEquity(p.equity_curve,mk.fills);
}
function crFeed(){const proto=location.protocol==='https:'?'wss:':'ws:';const ws=CRWS=new WebSocket(`${proto}//${location.host}/ws/trace`);
  ws.onopen=()=>ws.send(JSON.stringify({auth:TOK}));
  ws.onmessage=e=>{const jl=$('#crj');if(!jl){ws.close();return}let m;try{m=JSON.parse(e.data)}catch{return}if(m.channel!=='trace')return;
    $('#crjs').textContent='trace feed: connected (last '+m.data.length+' trace rows, server push)';
    const rows=m.data.slice(-12).map(r=>`<div class="${r.msg_type=='VETO'?'neg':r.stage=='fill'?'pos':''}"><span class="dim">${esc(r.agent_id)}</span> ${esc(r.stage)} ${esc(r.content)}</div>`).join('');
    let live=$('#crjlive');if(!live){live=document.createElement('div');live.id='crjlive';jl.prepend(live)}live.innerHTML=rows};
  ws.onclose=e=>{const s=$('#crjs');if(s)s.textContent='trace feed: '+(e.code===4401?'auth failed':'closed')}}
function crMk(el,h){const L=window.LightweightCharts;if(!L||!el)return null;const ch=L.createChart(el,{autoSize:true,height:h,layout:{background:{color:'#000'},textColor:'#aaa',fontFamily:'ui-monospace,monospace'},grid:{vertLines:{color:'#1a1a1a'},horzLines:{color:'#1a1a1a'}},timeScale:{timeVisible:true,borderColor:'#333'},rightPriceScale:{borderColor:'#333'}});CRCH.push(ch);return ch}
async function crPrice(){const c=await api('candles?symbol='+encodeURIComponent(CRSYM)+'&interval='+CRTF);
  const sel=$('#crsym');if(!sel)return;sel.innerHTML=c.symbols.map(x=>`<option ${x==CRSYM?'selected':''}>${esc(x)}</option>`).join('');sel.onchange=()=>{CRSYM=sel.value;render()};
  $('#crtf').innerHTML=[[60,'1m'],[300,'5m'],[900,'15m'],[3600,'1h']].map(([s,l])=>`<a class="crtfb ${s==CRTF?'on':''}" data-tf="${s}">${l}</a>`).join('');
  document.querySelectorAll('.crtfb').forEach(a=>a.onclick=()=>{CRTF=+a.dataset.tf;render()});
  $('#crpxl').textContent=c.label;const L=window.LightweightCharts;
  if(!c.candles.length){$('#crpx').innerHTML=ND;$('#crcd').innerHTML=ND;return}
  const data=c.candles.map(k=>({time:k.time,open:+k.open,high:+k.high,low:+k.low,close:+k.close}));
  const a=crMk($('#crpx'),170);if(a)a.addSeries(L.LineSeries,{color:'#00ff66',lineWidth:1}).setData(data.map(d=>({time:d.time,value:d.close})));
  const b=crMk($('#crcd'),300);if(b){const se=b.addSeries(L.CandlestickSeries,{upColor:'#00ff66',downColor:'#ff3355',wickUpColor:'#00ff66',wickDownColor:'#ff3355',borderVisible:false});se.setData(data);
    if(L.createSeriesMarkers&&c.fills.length){const t0=data[0].time,iv=CRTF;L.createSeriesMarkers(se,c.fills.filter(f=>f.ts>=t0).map(f=>({time:f.ts-f.ts%iv,position:f.side=='BUY'?'belowBar':'aboveBar',color:f.side=='BUY'?'#00ff66':'#ff3355',shape:f.side=='BUY'?'arrowUp':'arrowDown',text:'paper '+f.side})).sort((x,y)=>x.time-y.time))}}}
async function crBook(){let b;try{b=await api('book?symbol='+encodeURIComponent(CRSYM)+'&depth=10')}catch(e){$('#crbook').innerHTML=ND;return}
  const mx=Math.max(...b.bids.concat(b.asks).map(l=>+l[1]));const bar=(q,c)=>`<div class="crbar ${c}" style="width:${(+q/mx*100).toFixed(1)}%"></div>`;
  $('#crbook').innerHTML=`<div class="dim">${esc(b.label)} · ts ${esc(b.ts)} · mid ${esc(b.mid)} · spread ${(+b.spread_bps).toFixed(2)} bps</div>
  <table class="crtab book"><tr><th>bid qty</th><th>bid</th><th>ask</th><th>ask qty</th></tr>${b.bids.map((l,i)=>{const a=b.asks[i]||['',''];return `<tr><td class="pos">${bar(l[1],'b')}${esc(l[1])}</td><td class="pos">${esc(l[0])}</td><td class="neg">${esc(a[0])}</td><td class="neg">${a[1]?bar(a[1],'a'):''}${esc(a[1])}</td></tr>`}).join('')}</table>`}
function crEquity(curve,fills){const el=$('#creq');if(!curve||!curve.length){el.innerHTML=ND;return}
  const m=new Map();curve.forEach(([t,v])=>m.set(+t,+v));const data=[...m].sort((a,b)=>a[0]-b[0]).map(([time,value])=>({time,value}));
  const L=window.LightweightCharts;const ch=crMk(el,170);if(!ch)return;const up=data[data.length-1].value>=data[0].value;
  ch.addSeries(L.AreaSeries,{lineColor:up?'#00ff66':'#ff3355',topColor:up?'#00ff6655':'#ff335555',bottomColor:'#00000000',lineWidth:2}).setData(data)}
