const q=new URLSearchParams(location.search);if(q.get('token'))localStorage.tok=q.get('token');
const TOK=localStorage.tok||'';const H={Authorization:'Bearer '+TOK,'Content-Type':'application/json'};
const api=(p,o={})=>fetch('/api/'+p,{headers:H,...o}).then(async r=>{const j=await r.json().catch(()=>({}));if(!r.ok)throw {status:r.status,detail:j.detail};return j});
const $=s=>document.querySelector(s);const esc=s=>String(s??'—').replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const PAGES=['Command Center','Reactor','Floor','Crew Pool','Tickets & Trace','Markets','Research','India D5','Risk Console','Connectors','Approvals','Reports'];
let cur=decodeURIComponent(location.hash.slice(1))||PAGES[0],S={},timers=[];
$('#tabs').innerHTML=PAGES.map(p=>`<a data-p="${p}">${p}</a>`).join('');
document.querySelectorAll('#tabs a').forEach(a=>a.onclick=()=>{location.hash=a.dataset.p;});
window.onhashchange=()=>{cur=decodeURIComponent(location.hash.slice(1));render()};
setInterval(()=>$('#clock').textContent=new Date().toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'})+' IST',1000);
const sec=(t,body,cls='',tag='real')=>`<section class="${cls}"><h3>${t}<i class="${tag}">${tag=='real'?'REAL RUN DATA':tag=='demo'?'DEMO ANIMATION':tag.toUpperCase()}</i></h3>${body}</section>`;
const kv=o=>`<div class="kv">${Object.entries(o).map(([k,v])=>`<span>${esc(k)}</span><span>${esc(typeof v=='object'?JSON.stringify(v):v)}</span>`).join('')}</div>`;
function hdr(){const s=S;$('#hdr').innerHTML=`<div class="stats">
<div>MODE<span class="g">${s.mode}</span></div><div>PAPER NET PnL (after costs)<span class="${+s.net_pnl_after_costs<0?'r':'g'}">${s.net_pnl_after_costs} USDT</span></div>
<div>FEES PAID<span>${s.fees_paid}</span></div><div>FILLS / ROUND TRIPS<span>${s.fills} / ${s.round_trips}</span></div>
<div>WINS<span>${s.wins}/${s.round_trips}</span></div><div>VETOES<span>${s.vetoes}</span></div><div>RECON DRIFT<span>${s.recon_drift}</span></div>
<div>LIVE PnL<span class="dim">n/a (no live)</span></div><div>KILL<span class="${s.kill.engaged?'r':'g'}">${s.kill.engaged?'ENGAGED':'armed'}</span></div>
<div>LLM COST<span>$${s.cost.llm_cost_usd} (${s.cost.llm_tokens} tokens)</span></div></div>`}
function line(cv,pts,col){const c=cv.getContext('2d'),W=cv.width=cv.clientWidth,Hh=cv.height=cv.clientHeight;if(!pts.length)return;
const mn=Math.min(...pts),mx=Math.max(...pts);c.strokeStyle=col;c.lineWidth=2;c.shadowColor=col;c.shadowBlur=8;c.beginPath();
pts.forEach((v,i)=>{const x=i/(pts.length-1)*W,y=Hh-8-(v-mn)/((mx-mn)||1)*(Hh-16);i?c.lineTo(x,y):c.moveTo(x,y)});c.stroke();
c.shadowBlur=0;c.fillStyle='#889';c.fillText(mx.toFixed(2),4,10);c.fillText(mn.toFixed(2),4,Hh-2)}
async function render(){timers.forEach(clearInterval);timers=[];document.querySelectorAll('#tabs a').forEach(a=>a.classList.toggle('on',a.dataset.p==cur));
const P=$('#page');try{S=await api('summary');hdr()}catch(e){P.innerHTML=`<section class="w3"><h3>AUTH</h3>Open with ?token=&lt;viewer/operator/owner token from run_all.sh&gt; (${esc(e.status)})</section>`;return}
const who=await api('whoami');$('#role').textContent='role: '+who.role;
const f={'Command Center':cc,'Reactor':reactor,'Floor':floor,'Crew Pool':pool,'Tickets & Trace':tickets,'Markets':markets,'Research':research,'India D5':india,'Risk Console':riskp,'Connectors':conns,'Approvals':appr,'Reports':reports}[cur]||cc;
await f(P)}
async function cc(P){const [pnl,desks,ag]=await Promise.all([api('pnl'),api('desks'),api('agents')]);
P.innerHTML=sec('PAPER EQUITY (D4, net of fees+slippage, hourly marks)',`<canvas id="eq"></canvas><small>${esc(S.source)}</small>`,'w2')+
sec('HONESTY',kv({'paper net PnL':S.net_pnl_after_costs,'start → final':S.start_equity+' → '+S.final_equity,'avg slippage bps':S.avg_slippage_bps,'win rate':S.wins+'/'+S.round_trips+' (sample too small for a CI)','escalations':S.escalations,'live PnL':'none — paper and live are separate; live does not exist','strategy variants tried':(S.variants||[]).length,'agents enabled':S.agents_enabled+'/50'}))+
sec('DESKS',`<table><tr><th>desk</th><th>name</th><th>status</th></tr>${Object.values(desks).map(d=>`<tr><td>${d.desk}</td><td>${esc(d.name)}</td><td class="${d.desk=='D4'?'ok':'warn'}">${esc(d.status)}</td></tr>`).join('')}</table>`,'w2')+
sec('COST METER (metered, real)',kv({'LLM tokens':S.cost.llm_tokens,'LLM cost':'$'+S.cost.llm_cost_usd,'compute wall time (s)':S.cost.compute_wall_s,'note':S.cost.note}))+
sec('DAILY REALIZED PnL (USDT)',kv(pnl.paper.daily_pnl_realized))+sec('TICKET OUTCOMES',kv(S.ticket_outcomes))+sec('VARIANTS LOGGED',kv(Object.fromEntries((S.variants||[]).map(v=>['slope>'+v.regime_slope_threshold,v.result]))));
line($('#eq'),pnl.paper.equity_curve.map(x=>+x[1]),'#39ff9c')}
async function reactor(P){P.innerHTML=sec('REACTOR — tickets by final outcome through the stage ring',`<canvas id="rx" style="height:520px"></canvas>`,'w3 reactor');
const st=['DISCOVERED','ENRICHED','PRICED','RESEARCHED','RISK_CLEARED','APPROVED','ORDERED','FILLED','SETTLED','AUDITED'],o=S.ticket_outcomes,tot=Object.values(o).reduce((a,b)=>a+b,0);
const reached=[tot,tot,tot,tot,o.SETTLED+o.VETOED,o.SETTLED,o.SETTLED,o.SETTLED,o.SETTLED,tot];let a=0;
const cv=$('#rx');timers.push(setInterval(()=>{const c=cv.getContext('2d'),W=cv.width=cv.clientWidth,Hh=cv.height=cv.clientHeight,cx=W/2,cy=Hh/2,R=Math.min(W,Hh)*.36;a+=.01;
c.fillStyle='#07060f';c.fillRect(0,0,W,Hh);st.forEach((s,i)=>{const t=i/st.length*Math.PI*2-Math.PI/2,x=cx+R*Math.cos(t),y=cy+R*Math.sin(t);
c.strokeStyle='#a050ff';c.shadowColor='#a050ff';c.shadowBlur=14;c.beginPath();c.arc(x,y,16+reached[i]/tot*18,0,7);c.stroke();c.shadowBlur=0;
c.fillStyle='#fff';c.textAlign='center';c.fillText(s,x,y-40);c.fillStyle='#39ff9c';c.fillText(reached[i],x,y+4)});
c.strokeStyle='#39c4ff55';c.beginPath();c.arc(cx,cy,R,0,7);c.stroke();const t=a%(Math.PI*2)-Math.PI/2;c.fillStyle='#39c4ff';c.beginPath();c.arc(cx+R*Math.cos(t),cy+R*Math.sin(t),5,0,7);c.fill();
c.fillStyle='#ff4d6d';c.fillText(`REJECTED (no quorum) ${o.REJECTED}   VETOED ${o.VETOED}   SETTLED ${o.SETTLED}`,cx,cy);c.fillStyle='#667';c.fillText('counts are real; moving dot is decorative',cx,cy+18)},50))}
async function floor(P){const tr=await api('trace?limit=400');const crews={C1:'SPOTTER',C2:'PRIOR',C3:'EDGE',C4:'KELLY',C5:'TAKER',C6:'CLOSER',MAIN:'MAIN GROK'};
const last={};tr.forEach(r=>last[r.crew]=r);
P.innerHTML=sec('FLOOR — speech bubbles are the latest real trace row per crew; room art is decorative',`<canvas id="room" style="height:520px"></canvas>`,'w3');
const cv=$('#room'),cols=['#39ff9c','#39c4ff','#c79bff','#ff4d6d','#ffd23f','#ff8c42','#ffffff'];let f=0;
timers.push(setInterval(()=>{const c=cv.getContext('2d'),W=cv.width=cv.clientWidth,Hh=cv.height=cv.clientHeight;f++;c.fillStyle='#0a0818';c.fillRect(0,0,W,Hh);
for(let x=0;x<W;x+=24)for(let y=Hh*.35;y<Hh;y+=24){c.fillStyle=(x/24+y/24)%2<1?'#120e28':'#0e0a20';c.fillRect(x,y,24,24)}
Object.keys(crews).forEach((k,i)=>{const x=60+i*(W-120)/6,y=Hh*.55+(i%2)*60,col=cols[i];c.fillStyle='#2a1f55';c.fillRect(x-30,y,60,20);
c.fillStyle=col;c.fillRect(x-8,y-26+(f%40<20?0:1),16,22);c.fillStyle='#000';c.fillRect(x-24,y-14,18,12);c.fillStyle=col+'aa';c.fillRect(x-22,y-12,14,8);
c.fillStyle=col;c.font='11px monospace';c.textAlign='center';c.fillText(k+' '+crews[k],x,y+36);
const r=last[k];if(r){const txt=(r.agent_id+': '+r.content).slice(0,46);c.fillStyle='#fff';c.fillRect(x-80,y-80-(i%2)*20,160,28);c.fillStyle='#000';c.font='9px monospace';c.fillText(txt.slice(0,30),x,y-68-(i%2)*20);c.fillText(txt.slice(30),x,y-58-(i%2)*20)}})},100))}
async function pool(P){const ag=await api('agents');P.innerHTML=sec('CREW POOL — 50 sub-agents, live metrics from this run',`<div class="pool">${ag.map(a=>`<div class="card ${a.state}"><b>${a.id} ${esc(a.name)}</b> <span class="dim">${a.crew_name}</span><br>${esc(a.task)}<br>
<span class="${a.state=='ENABLED'?'ok':'warn'}">${a.state}</span> ${a.health}<br>calls ${a.calls} · err ${a.errors} · avg ${a.avg_ms??'—'}ms · q ${a.queue}<br>SLA ${a.sla_ms}ms · conc ${a.concurrency} · tokens ${a.llm_tokens}${a.reason?`<br><span class="dim">${esc(a.reason)}</span>`:''}</div>`).join('')}</div><small>* names after S23 inferred: pasted blueprint was truncated</small>`,'w3')}
async function tickets(P){const [t,tr]=await Promise.all([api('tickets'),api('trace?limit=200')]);
P.innerHTML=sec('TICKETS ('+t.length+')',`<div class="scroll"><table><tr><th>id</th><th>desk</th><th>instr</th><th>state</th><th>path</th></tr>${t.slice(-120).reverse().map(x=>`<tr><td>${x.id.slice(0,8)}</td><td>${x.desk}</td><td>${x.instrument}</td><td>${x.state}</td><td class="dim">${esc(x.history.map(h=>h[1]+(h[2]?' ('+h[2]+')':'')).join(' → '))}</td></tr>`).join('')}</table></div>`,'w2')+
sec('TRACE (append-only)',`<div class="scroll"><table>${tr.reverse().map(r=>`<tr><td>${r.agent_id}</td><td class="${r.msg_type=='VETO'||r.msg_type=='ESCALATE'?'bad':''}">${r.msg_type}</td><td>${esc(r.content)}</td></tr>`).join('')}</table></div>`)}
async function markets(P){const m=await api('markets');P.innerHTML=sec('PAPER FILLS',`<div class="scroll"><table><tr><th>time (IST)</th><th>sym</th><th>side</th><th>qty</th><th>px</th><th>fee</th><th>slip bps</th></tr>${m.fills.map(f=>`<tr><td>${new Date(f.ts*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})}</td><td>${f.symbol}</td><td class="${f.side=='BUY'?'ok':'bad'}">${f.side}</td><td>${f.qty}</td><td>${f.px}</td><td>${f.fee}</td><td>${f.slip_bps}</td></tr>`).join('')}</table></div><small>${esc(m.label)}</small>`,'w2')+sec('DATA QA (S09)',kv(m.qa))}
async function research(P){const r=await api('research');P.innerHTML=['D1','D2','D3'].map(k=>sec(k+' — SYNTHETIC FIXTURE, NOT_APPROVED_BY_OWNER, REPLAY-locked',`<pre style="white-space:pre-wrap;font-size:10px">${esc(JSON.stringify(r[k],null,1))}</pre>`,'','synthetic')).join('')}
async function india(P){const d=await api('india');if(d.error){P.innerHTML=sec('D5 INDIA',esc(d.error),'w3');return}
const rp=d.replay;P.innerHTML=sec('D5 INDIA NSE — '+esc(rp.status),kv(d.gate0),'','locked')+
sec('SEBI / GO-LIVE GATE CHECKLIST (all must pass to leave REPLAY)',`<table>${d.sebi.checklist.map(c=>`<tr><td class="${c.ok?'ok':'bad'}">${c.ok?'PASS':'BLOCKED'}</td><td>${c.gate}</td><td>${esc(c.detail)}</td></tr>`).join('')}</table><p class="${d.sebi.may_leave_replay?'ok':'bad'}">may leave REPLAY: ${d.sebi.may_leave_replay}</p>`)+
sec('REPLAY OF RISK/UNIVERSE/TIMING CHECKS (bhavcopy)',kv({label:rp.label,sessions:rp.sessions,range:rp.first+' → '+rp.last,'universe ok/fail':rp.universe_ok+'/'+rp.universe_fail,'pre-universe date':rp.pre_universe_date,'calendar':rp.production_calendar,probes:rp.probe_count}))+
sec('PROBE INTENTS (not a strategy, no PnL)',`<div class="scroll"><table><tr><th>date</th><th>isin</th><th>size</th><th>10:00 CNC</th><th>14:59</th><th>15:00</th><th>MIS</th><th>calendar</th></tr>${rp.probes.map(p=>`<tr><td>${p.date}</td><td>${p.isin}</td><td>${p.size.join(' ')}</td><td>${p['10:00 CNC']}</td><td>${p['14:59 CNC']}</td><td>${p['15:00 CNC']}</td><td>${p['10:00 MIS']}</td><td class="bad">${p.calendar_entry}</td></tr>`).join('')}</table></div>`,'w3','locked')}
async function riskp(P){const r=await api('risk');P.innerHTML=sec('KILL SWITCH',`<p>State: <b class="${r.kill.engaged?'r':'g'}">${r.kill.engaged?'ENGAGED — '+esc(r.kill.reason):'armed'}</b></p><button class="kill" id="kb">ENGAGE KILL SWITCH</button><p class="dim">Operator or owner token required. Halts all desks, marks open tickets, blocks new orders. Reset needs a signed owner approval.</p><p id="km"></p>`)+
sec('HARD LIMITS (file-only, sha256 '+r.limits_sha256.slice(0,12)+'…, file ok: '+r.limits_file_ok+')',kv(r.limits))+
sec('DRILLS (latest real run)',`<table>${Object.entries(r.drills).map(([k,v])=>`<tr><td>${k}</td><td class="${v.passed?'ok':'bad'}">${v.passed?'PASS':'FAIL'}</td></tr>`).join('')}</table><button id="dr">re-run drills</button>`)+
sec('RISK EVENTS / VETOES',`<div class="scroll"><table>${r.risk_events.slice().reverse().map(e=>`<tr><td>${e[2]}</td><td>${esc(e[4])}</td></tr>`).join('')||'<tr><td class="dim">no risk events in this run</td></tr>'}</table></div>`,'w3');
$('#kb').onclick=async()=>{if(!confirm('Engage kill switch?'))return;try{await api('kill',{method:'POST',body:JSON.stringify({reason:'manual kill from Risk Console'})});render()}catch(e){$('#km').textContent='refused: '+e.status+' '+JSON.stringify(e.detail)}};
$('#dr').onclick=async()=>{try{await api('drills/run',{method:'POST'});render()}catch(e){alert('refused '+e.status)}}}
async function conns(P){const c=await api('connectors');P.innerHTML=sec('CONNECTORS (no network in this build)',`<table><tr><th>name</th><th>kind</th><th>mode</th><th>health</th><th>latency ms</th><th>docs verified</th><th>notes</th><th></th></tr>${c.map(x=>`<tr><td>${x.name}</td><td>${x.kind}</td><td>${x.mode}</td><td class="${x.health.status=='OK'?'ok':'warn'}">${x.health.status} ${esc(x.health.detail)}</td><td>${x.latency_ms}</td><td>${x.docs_verified}</td><td class="dim">${esc(x.notes)}</td><td><button data-n="${x.name}">Test</button></td></tr>`).join('')}</table><p id="ct"></p>`,'w3');
document.querySelectorAll('button[data-n]').forEach(b=>b.onclick=async()=>{$('#ct').textContent=b.dataset.n+': '+JSON.stringify(await api('connectors/'+b.dataset.n+'/test',{method:'POST'}))})}
async function appr(P){const [a,m]=await Promise.all([api('approvals'),api('mode')]);P.innerHTML=sec('MODE LADDER',kv({current:m.mode,ladder:m.ladder.join(' → '),'API cap':m.api_cap,'LIVE_AUTO':'owner policy: not enabled'}))+
sec('REQUEST SIGNED APPROVAL (owner only)',`<p>Subject <input id="sub" value="promote:PAPER->LIVE_APPROVAL" style="width:70%;background:#000;color:#fff;border:1px solid #2a1f55"></p><button id="ap">APPROVE (sign)</button> <button id="rj">REJECT</button><p class="dim">A signed approval is necessary but not sufficient: gates still apply.</p><pre id="ar" style="white-space:pre-wrap"></pre>`)+
sec('APPROVAL LOG',`<table>${a.map(x=>`<tr><td>${esc(x.subject)}</td><td>${x.decision}</td><td>${x.verified?'signed ✓':'unsigned'}</td><td>${esc(x.gate_result?JSON.stringify(x.gate_result):'')}</td></tr>`).join('')||'<tr><td class="dim">none</td></tr>'}</table>`);
const go=d=>async()=>{try{$('#ar').textContent=JSON.stringify(await api('approvals',{method:'POST',body:JSON.stringify({subject:$('#sub').value,decision:d})}),null,1)}catch(e){$('#ar').textContent='refused '+e.status+' '+JSON.stringify(e.detail)}};$('#ap').onclick=go('APPROVE');$('#rj').onclick=go('REJECT')}
async function reports(P){const r=await api('reports');P.innerHTML=sec('GENERATED REPORTS',`<table>${r.map(n=>`<tr><td><a href="#" data-r="${n}" style="color:#39c4ff">${n}</a></td></tr>`).join('')}</table>`)+sec('VIEW','<pre id="rv" style="white-space:pre-wrap;font-size:10px;max-height:600px;overflow:auto"></pre>','w2');
document.querySelectorAll('a[data-r]').forEach(a=>a.onclick=async e=>{e.preventDefault();$('#rv').textContent=await fetch('/api/reports/'+a.dataset.r,{headers:H}).then(r=>r.text())});const md=r.filter(n=>n.startsWith('paper-day')&&n.endsWith('.md')).pop();if(md)$('#rv').textContent=await fetch('/api/reports/'+md,{headers:H}).then(r=>r.text())}
render();setInterval(async()=>{try{S=await api('summary');hdr()}catch(e){}},5000);
