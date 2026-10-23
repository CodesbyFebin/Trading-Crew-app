// GROK DESK skin (final default Control Room view). Layout inspired by an owner-supplied mock; NONE of its data is used.
// Rules (tests/test_ui_real_data.py): no random sources, no timers that change numbers, no CDNs. All text is written once
// per render() from this server's API; the requestAnimationFrame loop only redraws decorative canvas geometry.
let GD={raf:0};
const GND='<span class="nd">NO DATA</span>';
const gv=v=>v===null||v===undefined||v===''||(typeof v=='number'&&isNaN(v))?GND:esc(v);
const gsg=v=>+v>0?'pos':+v<0?'neg':'';
const GCOL=['#6366f1','#0ea5e9','#10b981','#f59e0b','#ec4899','#8b5cf6'];
const GSHAPE=['circle','diamond','triangle','square','hex','pill'];
function gdMascot(i,col){const s=GSHAPE[i%6],P={circle:'<circle cx="24" cy="24" r="18"/>',diamond:'<polygon points="24,4 44,24 24,44 4,24"/>',triangle:'<polygon points="24,4 44,42 4,42"/>',square:'<rect x="6" y="6" width="36" height="36" rx="4"/>',hex:'<polygon points="24,3 42,13 42,35 24,45 6,35 6,13"/>',pill:'<rect x="8" y="4" width="32" height="40" rx="16"/>'}[s];
  return `<svg class="gdm" viewBox="0 0 48 48" aria-hidden="true"><g fill="${col}">${P}</g><rect x="17" y="18" width="4" height="10" rx="2" fill="#fff"/><rect x="27" y="18" width="4" height="10" rx="2" fill="#fff"/></svg>`}
function gdEye(){return `<svg class="gdeye" viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="18" fill="none" stroke="currentColor" stroke-width="3"/><circle cx="20" cy="20" r="7" fill="currentColor"/><circle cx="22.5" cy="17.5" r="2" fill="#fff"/></svg>`}
function gdCard(t,body,cls=''){return `<div class="gdc ${cls}"><div class="gdt">${t}</div>${body}</div>`}
async function grokDesk(P){
  cancelAnimationFrame(GD.raf);CRCH.forEach(c=>{try{c.remove()}catch{}});CRCH=[];
  const [pnl,pipe,risk,mk,ag,desks,tr,audit,tk,execution]=await Promise.all([api('pnl'),api('pipeline'),api('risk'),api('markets'),api('agents'),api('desks'),api('trace?limit=2000'),api('audit'),api('tickets'),api('execution/status')]);
  let book=null;try{book=await api('book?symbol='+encodeURIComponent(CRSYM)+'&depth=8')}catch(e){}
  const p=pnl.paper,fills=mk.fills||[],theme=localStorage.gdTheme==='dark'?'dark':'light';
  const crews=[];ag.forEach(a=>{let c=crews.find(x=>x.id==a.crew);if(!c)crews.push(c={id:a.crew,name:a.crew_name,n:0,on:0,ok:0,err:0,last:null});c.n++;if(a.state=='ENABLED')c.on++;if(a.health=='OK')c.ok++;c.err+=+a.errors});
  tr.forEach(r=>{const c=crews.find(x=>x.id==r.crew);if(c)c.last=r.ts});
  const eqC=(p.equity_curve||[]).map(x=>+x[1]);let pk=-Infinity,dd=0;eqC.forEach(v=>{pk=Math.max(pk,v);dd=Math.max(dd,pk-v)});
  let cf=0;const feeS=[],notS=[];fills.forEach(f=>{cf+=+f.fee;feeS.push(cf);notS.push(+f.qty*+f.px)});
  const okStages=pipe.stages.filter(s=>s.status=='OK'||s.status=='ARMED').length;
  const evs=audit.slice(-15).map(a=>`AUDIT ${a[2]} ${a[3]} ${a[4]}`).concat(tr.slice(-15).map(r=>`${r.agent_id} ${r.stage} ${r.content}`));
  const exhaust=mk.vetoes.map(v=>'VETO '+v.symbol+' '+v.reasons.join('; ')).concat(risk.risk_events.map(e=>e[2]+' '+e[4]));
  const lastT=tk.length?tk[tk.length-1]:null,lastF=fills.length?fills[fills.length-1]:null,rt=S.round_trips;
  const DV=Object.values(desks),dOn=DV.filter(d=>/^PAPER/.test(d.status)),dOff=DV.filter(d=>!/^PAPER/.test(d.status));
  const deskNames=dOn.map(d=>d.desk+' '+d.name+' · PAPER').join(' · ')+(dOff.length?' · '+dOff.map(d=>d.desk).join('/')+' not approved (replay only)':'');
  const feeds=[['FILLS · NOTIONAL PER FILL',S.fills,notS],['PAPER EQUITY MTM',p.final_equity_mtm,eqC],['FEES PAID (CUMULATIVE)',p.fees_paid,feeS],
    ['BOOK '+CRSYM+' MID / SPREAD BPS',book?`${book.mid} / ${(+book.spread_bps).toFixed(2)}`:null,null],['RECON DRIFT',p.reconciliation_drift,null],['PIPELINE STAGES OK/ARMED',`${okStages}/${pipe.stages.length}`,null]];
  // signal heatmap: real per-agent runtime metrics (calls, avg ms, errors, SLA breaches) from /api/agents
  const hm=['calls','avg_ms','errors','sla_breaches'],hmx=Object.fromEntries(hm.map(k=>[k,Math.max(...ag.map(a=>+a[k]||0))]));
  const handoffs=[];for(let i=1;i<tr.length&&handoffs.length<400;i++)if(tr[i].ticket_id==tr[i-1].ticket_id&&tr[i].agent_id!=tr[i-1].agent_id)handoffs.push([tr[i-1],tr[i]]);
  P.innerHTML=`<section class="w3 gd ${theme}">
  <div class="gdhead">${gdEye()}<div><div class="gdtitle">GROK DESK</div><div class="gdsub">${esc(deskNames)}</div></div>
   <div class="gdhr"><span class="crbadge">MODE ${esc(execution.current_mode)}</span><span class="crbadge ${execution.order_submission_available?'':'r'}">${execution.order_submission_available?'EXECUTION READY':'EXECUTION NOT CONFIGURED'}</span><span id="crclock" class="gdclk"></span>
   <a class="gdth" id="gdth">${theme=='dark'?'☀ LIGHT':'☾ DARK'}</a> ${sphSkinBar()}</div></div>
  <div class="gdwire" aria-label="live wire: latest audit and trace rows of this run"><b>LIVE WIRE</b><div class="gdmq"><div class="gdmqi">${evs.length?evs.map(e=>`<span>${esc(e)}</span>`).join(''):'NO DATA'}${evs.map(e=>`<span aria-hidden="true">${esc(e)}</span>`).join('')}</div></div></div>
  <div class="gdcrews">${crews.map((c,i)=>`<a class="gdcrew" data-crew="${esc(c.id)}" title="open Crew Pool">${gdMascot(i,GCOL[i%6])}<b>${esc(c.name)}</b><span>${esc(c.id)} · ${c.on}/${c.n} enabled</span><small>last trace ${c.last?esc(c.last.slice(11,19))+' UTC':'NO DATA'}</small></a>`).join('')||GND}</div>
  <div class="gdreact">
   <div class="gdfeeds">${gdCard('REACTOR FEEDS',feeds.map(([k,v,s],i)=>`<div class="gdfeed"><span>${k}</span><b>${gv(v)}</b>${s&&s.length>1?`<canvas class="gdspk" data-i="${i}"></canvas>`:'<small class="dim">no series</small>'}</div>`).join(''))}</div>
   <div class="gdring"><canvas id="gdring" aria-hidden="true"></canvas><div class="gdrl"><b>${ag.filter(a=>a.state=='ENABLED').length}/${ag.length}</b><span>AGENTS ENABLED · ${crews.length} CREWS</span></div></div>
   <div class="gdstack">${gdCard('LAST TICKET / FILL',`<div>${lastT?`${esc(lastT.desk)} ${esc(lastT.instrument)} · ${esc(lastT.state)}`:GND}</div><div>${lastF?`${esc(lastF.side)} ${esc(lastF.qty)} ${esc(lastF.symbol)} @ ${esc(lastF.px)} · fee ${esc(lastF.fee)}`:GND}</div>`)}
    ${gdCard('CREW HEALTH (agents OK / total)',crews.map((c,i)=>`<div class="gdhb"><span>${esc(c.name)}</span><i><u style="width:${(c.ok/c.n*100).toFixed(0)}%;background:${GCOL[i%6]}"></u></i><b>${c.ok}/${c.n}</b></div>`).join(''))}
    ${gdCard('EXHAUST · RISK EVENTS + VETOES',exhaust.length?exhaust.slice(-8).map(e=>`<div class="neg">${esc(e)}</div>`).join(''):`<div class="dim">${esc(S.vetoes)} vetoes, 0 risk events this run · kill ${risk.kill.engaged?'ENGAGED':'ARMED'}</div>`)}</div>
  </div>
  <div class="gdpnl">${gdCard('SWARM PNL · D4 PAPER (after costs)',`<div class="gdbig">${gv(p.final_equity_mtm)} <small>USDT</small> <span class="${gsg(p.net_pnl_after_costs)}">${gv(p.net_pnl_after_costs)}</span></div>
    <div class="gdkpi">${[['TICKETS',tk.length],['WIN RATE',rt?`${S.wins}/${rt}`:null],['AVG PER TRIP',rt?(+p.net_pnl_after_costs/rt).toFixed(4):null],['MAX DD (equity curve)',eqC.length?dd.toFixed(4):null],['FEES',p.fees_paid],['AVG SLIP BPS',p.avg_slippage_bps]].map(([k,v])=>`<div><span>${k}</span><b>${gv(v)}</b></div>`).join('')}</div><div id="creq" class="gdch"></div>`)}</div>
  <div class="gdtape">${gdCard('THE TAPE · '+esc(CRSYM)+' · synthetic replay sample, not real market data','<div id="crcd" class="gdch tall"></div>','gdt1')}
   ${gdCard('ORDER-BOOK LADDER · offline replay snapshot',book?`<table class="gdtab"><tr><th>bid qty</th><th>bid</th><th>ask</th><th>ask qty</th></tr>${book.bids.map((l,i)=>{const a=book.asks[i]||['',''];return `<tr><td>${esc(l[1])}</td><td class="pos">${esc(l[0])}</td><td class="neg">${esc(a[0])}</td><td>${esc(a[1])}</td></tr>`}).join('')}</table><small class="dim">${esc(book.label)}</small>`:GND)}</div>
  <div class="gdbot">${gdCard('THE TRACE · agent handoffs ('+handoffs.length+')',handoffs.length?`<div class="gdlog">${handoffs.slice(-14).map(([a,b])=>`<div><b>${esc(a.agent_id)}</b> → <b>${esc(b.agent_id)}</b> <span class="dim">${esc(b.stage)}</span> ${esc(b.content)}</div>`).join('')}</div>`:GND)}
   ${gdCard('THE PRICER',`${GND}<p class="dim">No probability distribution is produced by this paper run, so nothing is plotted.</p>`)}
   ${gdCard('SIGNAL HEATMAP · per-agent runtime metrics',`<div class="gdhm"><span></span>${hm.map(k=>`<span class="dim">${k}</span>`).join('')}${ag.map(a=>`<span>${esc(a.id)}</span>${hm.map(k=>{const v=+a[k]||0,f=hmx[k]?v/hmx[k]:0;return `<i style="background:rgba(99,102,241,${(0.08+f*0.85).toFixed(2)})" title="${esc(a.id+' '+k+' '+a[k])}">${esc(a[k])}</i>`}).join('')}`).join('')}</div>`)}</div>
  </section>`;
  sphSkinWire();const gc=$('#clock');if(gc)$('#crclock').textContent=gc.textContent;
  $('#gdth').onclick=()=>{localStorage.gdTheme=theme=='dark'?'light':'dark';render()};
  document.querySelectorAll('.gdcrew').forEach(a=>a.onclick=()=>{location.hash='Crew Pool'});
  document.querySelectorAll('canvas.gdspk').forEach(c=>sphSpark(c,feeds[+c.dataset.i][2],GCOL[+c.dataset.i%6]));
  crEquity(p.equity_curve,fills);await gdCandles();gdRing(crews.length||6,theme);
  const dk=theme=='dark';CRCH.forEach(ch=>{try{ch.applyOptions({layout:{background:{color:dk?'#0f172a':'#ffffff'},textColor:dk?'#cbd5e1':'#334155'},grid:{vertLines:{color:dk?'#1e293b':'#f1f5f9'},horzLines:{color:dk?'#1e293b':'#f1f5f9'}}})}catch{}});
}
async function gdCandles(){const c=await api('candles?symbol='+encodeURIComponent(CRSYM)+'&interval='+CRTF),el=$('#crcd');if(!el)return;if(!c.candles.length){el.innerHTML=GND;return}
  const L=window.LightweightCharts,data=c.candles.map(k=>({time:k.time,open:+k.open,high:+k.high,low:+k.low,close:+k.close}));const ch=crMk(el,260);if(!ch)return;
  const se=ch.addSeries(L.CandlestickSeries,{upColor:'#10b981',downColor:'#f43f5e',wickUpColor:'#10b981',wickDownColor:'#f43f5e',borderVisible:false});se.setData(data);
  if(L.createSeriesMarkers&&c.fills.length){const t0=data[0].time;L.createSeriesMarkers(se,c.fills.filter(f=>f.ts>=t0).map(f=>({time:f.ts-f.ts%CRTF,position:f.side=='BUY'?'belowBar':'aboveBar',color:f.side=='BUY'?'#10b981':'#f43f5e',shape:f.side=='BUY'?'arrowUp':'arrowDown',text:'paper '+f.side})).sort((x,y)=>x.time-y.time))}}
function gdRing(n,theme){const cv=$('#gdring');if(!cv)return;const still=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
  const frame=ts=>{if(!document.body.contains(cv))return;const t=still?0:ts||0,W=cv.width=cv.clientWidth,H=cv.height=cv.clientHeight,c=cv.getContext('2d'),cx=W/2,cy=H/2,R=Math.min(W,H)*0.36;
    c.clearRect(0,0,W,H);c.lineWidth=2;c.strokeStyle=theme=='dark'?'#334155':'#cbd5e1';c.beginPath();c.arc(cx,cy,R,0,6.283);c.stroke();
    for(let i=0;i<n;i++){const a=i/n*6.283+t*0.0002,x=cx+R*Math.cos(a),y=cy+R*Math.sin(a);c.strokeStyle=GCOL[i%6];
      for(let k=0;k<5;k++){c.beginPath();c.ellipse(x,y,14-k*1.5,6,a+k*0.35+t*0.001,0,6.283);c.stroke()}}
    const sr=R*0.42;const g=c.createRadialGradient(cx-sr*0.3,cy-sr*0.3,2,cx,cy,sr);g.addColorStop(0,'#a5b4fc');g.addColorStop(1,'#4338ca');c.fillStyle=g;c.beginPath();c.arc(cx,cy,sr,0,6.283);c.fill();
    const bl=Math.abs(Math.sin(t*0.0007))>0.97?0.15:1;c.fillStyle='#fff';[-1,1].forEach(s=>{c.beginPath();c.ellipse(cx+s*sr*0.28,cy-sr*0.1,sr*0.09,sr*0.22*bl,0,0,6.283);c.fill()});
    if(!still)GD.raf=requestAnimationFrame(frame)};GD.raf=requestAnimationFrame(frame)}
