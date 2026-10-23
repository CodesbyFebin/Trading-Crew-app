// Sphere skin for the Control Room. Cloned look from a concept video; every number/label comes from this server's API.
// Rules (tests/test_ui_real_data.py): no random sources, no timers that change numbers. Text is written once per render();
// the requestAnimationFrame loop only redraws canvas geometry (sphere rotation, connection lines, decorative jellyfish).
// Decorative geometry uses a seeded PRNG (mulberry32) so it is identical on every load.
let SPH={raf:0,alive:false};
const SND='<span class="nd">NO DATA</span>';
const sv=v=>v===null||v===undefined||v===''?SND:esc(v);
function sphRng(seed){let a=seed>>>0;return()=>{a=a+0x6D2B79F5>>>0;let t=a;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296}}
function sphSpark(el,pts,col){if(!el)return;if(!pts||pts.length<2){el.outerHTML=SND;return}
  const c=el.getContext('2d'),W=el.width=el.clientWidth||90,H=el.height=el.clientHeight||22,mn=Math.min(...pts),mx=Math.max(...pts);
  c.strokeStyle=col;c.lineWidth=1.2;c.beginPath();pts.forEach((v,i)=>{const x=i/(pts.length-1)*(W-2)+1,y=H-2-(v-mn)/((mx-mn)||1)*(H-4);i?c.lineTo(x,y):c.moveTo(x,y)});c.stroke()}
function sphRoute(P){const k=localStorage.crSkin||'grokdesk';return k==='sphere'?sphereRoom(P):k==='classic'?controlRoom(P):grokDesk(P)}
function sphSkinBar(){const s=localStorage.crSkin||'grokdesk';
  return `<span class="skinbar">SKIN ${[['classic','CONTROL ROOM'],['sphere','SPHERE'],['grokdesk','GROK DESK']].map(([k,l])=>`<a class="skb ${s==k?'on':''}" data-skin="${k}">${l}</a>`).join('')}</span>`}
function sphSkinWire(){document.querySelectorAll('.skb').forEach(a=>a.onclick=()=>{localStorage.crSkin=a.dataset.skin;render()})}
async function sphereRoom(P){
  SPH.alive=false;cancelAnimationFrame(SPH.raf);
  const [pnl,pipe,risk,mk,ag,desks,tr,execution]=await Promise.all([api('pnl'),api('pipeline'),api('risk'),api('markets'),api('agents'),api('desks'),api('trace?limit=2000'),api('execution/status')]);
  const p=pnl.paper,fills=mk.fills||[];
  const crews=[];ag.forEach(a=>{let c=crews.find(x=>x.id==a.crew);if(!c)crews.push(c={id:a.crew,name:a.crew_name,n:0,on:0,ms:0,calls:0});c.n++;if(a.state=='ENABLED')c.on++;c.ms+=+a.avg_ms*+a.calls;c.calls+=+a.calls});
  const enabled=ag.filter(a=>a.state=='ENABLED').length;
  const states={};ag.forEach(a=>states[a.state]=(states[a.state]||0)+1);
  let cf=0,cn=0;const feeS=[],notS=[],slS=[];fills.forEach(f=>{cf+=+f.fee;cn+=+f.qty*+f.px;feeS.push(cf);notS.push(cn);slS.push(+f.slip_bps)});
  const eq=(p.equity_curve||[]).map(x=>+x[1]);
  const lanes=tr.filter(r=>r.stage=='lane'),arb=tr.filter(r=>r.stage=='arbiter');
  const vetoItems=mk.vetoes.map(v=>'VETO '+v.symbol+' '+v.reasons.join('; ')).concat(risk.risk_events.map(e=>e[2]+' '+e[4]));
  const flows=[['NET PNL AFTER COSTS',p.net_pnl_after_costs,eq],['FEES PAID',p.fees_paid,feeS],['FILLS NOTIONAL',fills.length?cn.toFixed(2):null,notS],
    ['AVG SLIPPAGE BPS',p.avg_slippage_bps,slS],['RECON DRIFT',p.reconciliation_drift,null],['FINAL EQUITY MTM',p.final_equity_mtm,eq]];
  const col=(t,items,hl)=>`<div class="sdcol"><div class="sdh">${t}</div>${items.length?items.map((x,i)=>`<div class="sdi ${i==hl?'hl':''}">${esc(x)}</div>`).join(''):`<div class="sdi">${SND}</div>`}</div>`;
  const ICON=['◎','◇','△','▣','▶','■'];
  P.innerHTML=`<section class="w3 sph">
  <canvas id="sphjelly" class="sphjelly" aria-hidden="true"></canvas>
  <div class="sphtop">
   <div class="sphtl"><div class="sphtitle">GROK TRADING CREW - CONTROL SPHERE</div>
    <div><span class="crbadge">MODE ${esc(execution.current_mode)}</span><span class="crbadge ${execution.order_submission_available?'':'r'}">${execution.order_submission_available?'EXECUTION READY':'EXECUTION NOT CONFIGURED'}</span> ${sphSkinBar()}</div>
    <div class="dim">MODE ${esc(S.mode)} · RUN ${esc((pipe.run_id||'').slice(0,8))||'NO DATA'} · <span id="crclock"></span></div></div>
   <div class="sphctr"><div class="sphk">PAPER FILLS</div><div class="sphbig">${sv(S.fills)}</div><div class="sphk">DECISIONS ${sv(arb.length)}</div></div>
   <div class="sphstats">${[['ROUND TRIPS',S.round_trips],['WINS',S.wins],['VETOES',S.vetoes],['INTENTS',pipe.intents_submitted],['LANE VERDICTS',lanes.length],['KILL',risk.kill.engaged?'ENGAGED':'ARMED']].map(([k,v])=>`<div><span class="sphk">${k}</span><b>${sv(v)}</b></div>`).join('')}</div>
   <div class="sphline"><div class="sphk">LINE OF A DECISION · PAPER EQUITY</div><canvas id="sphlod"></canvas></div>
   <div class="sphblk"><div class="sphk">BLOCK STACK · ${ag.length} AGENTS</div><div class="blk">${ag.map(a=>`<i title="${esc(a.id+' '+a.name+' '+a.state)}" class="${a.state=='ENABLED'?(a.health=='OK'?'ok':'bad'):a.state=='NOT_APPROVED_BY_OWNER'?'na':'off'}"></i>`).join('')}</div></div>
  </div>
  <div class="sphmid">
   <div class="sphflows"><div class="sdh">FLOWS</div>${flows.map(([k,v,s],i)=>`<div class="flow"><span class="fk">${k}</span><b class="${+v<0?'neg':''}">${sv(v)}</b>${s?`<canvas class="spk" data-i="${i}"></canvas>`:'<span class="spk">'+SND+'</span>'}<span class="fnode"></span></div>`).join('')}</div>
   <div class="sphcore"><canvas id="sphcv" aria-hidden="true"></canvas><div class="sphlbl"><b>${sv(enabled)} STATES</b><span>ENABLED OF ${sv(ag.length)} AGENTS</span></div></div>
   <div class="sphdec"><div class="sdh">DECISION STACK</div><div class="sdcols">
    ${col('L1 · LANES',lanes.slice(-8).map(r=>r.agent_id+' '+r.content),lanes.length?Math.min(lanes.length,8)-1:-1)}
    ${col('L2 · RISK VETOES',vetoItems.length?vetoItems.slice(-8):[S.vetoes+' VETOES · NO RISK EVENTS THIS RUN'],vetoItems.length?0:-1)}
    ${col('L3 · MAIN GROK',arb.slice(-8).map(r=>r.content.replace(/^rationale: /,'')),arb.length?Math.min(arb.length,8)-1:-1)}</div></div>
  </div>
  <div class="sphbot">
   <div class="sphag"><div class="sdh">AGENTS · CREWS</div><div class="agb">${crews.map((c,i)=>`<div class="agx"><span class="agi">${ICON[i%6]}</span><b>${esc(c.name)}</b><span>${esc(c.id)} · ${c.on}/${c.n} ON</span></div>`).join('')||SND}</div></div>
   <div class="sphres"><div class="sdh">RESOURCE STATES · AGENTS BY STATE</div>${Object.entries(states).map(([k,v])=>`<div class="rbar"><span>${esc(k)}</span><i style="width:${(v/ag.length*100).toFixed(1)}%"></i><b>${v}</b></div>`).join('')||SND}</div>
   <div class="sphyld"><div class="sdh">STATE YIELDS · PER DESK</div><table class="crtab"><tr><th>DESK</th><th>STATUS</th><th>NET PNL</th></tr>${Object.values(desks).map(d=>`<tr><td>${esc(d.desk)} ${esc(d.name)}</td><td class="dim">${esc(d.status)}</td><td>${d.desk=='D4'?`<span class="${+p.net_pnl_after_costs<0?'neg':'pos'}">${esc(p.net_pnl_after_costs)}</span>`:SND}</td></tr>`).join('')}</table></div>
  </div></section>`;
  sphSkinWire();const gc=$('#clock');if(gc)$('#crclock').textContent=gc.textContent;
  document.querySelectorAll('canvas.spk').forEach(c=>sphSpark(c,flows[+c.dataset.i][2],'#00FFFF'));
  sphSpark($('#sphlod'),eq,'#FF00FF');
  sphAnimate(Math.max(enabled,1));
}
function sphAnimate(nRays){
  const cv=$('#sphcv'),jc=$('#sphjelly'),root=$('.sph');if(!cv||!jc)return;
  const R=sphRng(20261020),rays=[];for(let i=0;i<Math.min(nRays*6,360);i++){const u=R()*2-1,t=R()*6.283;const s=Math.sqrt(1-u*u);rays.push([s*Math.cos(t),u,s*Math.sin(t),0.55+R()*0.45])}
  const jel=[0,1,2,3].map(i=>({x:R(),y:R(),r:30+R()*40,ph:R()*6.283,sp:0.00003+R()*0.00003}));
  const still=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;SPH.alive=true;
  const frame=ts=>{if(!SPH.alive||!document.body.contains(cv))return;const t=still?0:ts||0;
    const W=cv.width=cv.clientWidth,H=cv.height=cv.clientHeight,c=cv.getContext('2d'),cx=W/2,cy=H/2,rad=Math.min(W,H)*0.42,a=t*0.00015;
    c.clearRect(0,0,W,H);c.setLineDash([2,4]);
    for(const [x,y,z,l] of rays){const X=x*Math.cos(a)+z*Math.sin(a),Z=-x*Math.sin(a)+z*Math.cos(a),d=(Z+1.6)/2.6;
      c.strokeStyle=Z>0?`rgba(0,255,255,${0.25+0.6*d})`:`rgba(160,192,208,${0.15*d+0.05})`;c.beginPath();c.moveTo(cx+X*rad*0.15,cy+y*rad*0.15);c.lineTo(cx+X*rad*l,cy+y*rad*l);c.stroke();
      if(Z>0.3){c.fillStyle='#FFB6C1';c.fillRect(cx+X*rad*l-1,cy+y*rad*l-1,2,2)}}
    c.setLineDash([]);c.strokeStyle='rgba(75,0,130,0.9)';c.beginPath();c.ellipse(cx,cy,rad,rad*0.3,0,0,6.283);c.stroke();
    // connection lines from flow nodes to the sphere (overlay = jelly canvas, page coords)
    const bw=jc.width=root.clientWidth,bh=jc.height=root.clientHeight,j=jc.getContext('2d'),rb=root.getBoundingClientRect(),cb=cv.getBoundingClientRect();
    j.clearRect(0,0,bw,bh);j.strokeStyle='rgba(0,255,255,0.35)';j.setLineDash([3,3]);j.lineDashOffset=-t*0.01;
    document.querySelectorAll('.fnode').forEach(n=>{const b=n.getBoundingClientRect();if(!b.width||cb.width<10)return;j.beginPath();j.moveTo(b.left-rb.left+4,b.top-rb.top+4);j.lineTo(cb.left-rb.left+cb.width/2-rad*0.9,cb.top-rb.top+cb.height/2);j.stroke()});
    j.setLineDash([]);
    for(const q of jel){const x=((q.x+t*q.sp)%1)*bw,y=(q.y+0.04*Math.sin(t*0.0004+q.ph))*bh,r=q.r,pu=1+0.08*Math.sin(t*0.002+q.ph);
      j.strokeStyle='rgba(255,0,255,0.28)';j.beginPath();j.ellipse(x,y,r*pu,r*0.6,0,Math.PI,0);j.stroke();
      for(let k=0;k<5;k++){const ox=x-r+k*r/2;j.strokeStyle='rgba(255,182,193,0.18)';j.beginPath();j.moveTo(ox,y);for(let s=1;s<=6;s++)j.lineTo(ox+5*Math.sin(t*0.002+k+s),y+s*r*0.25);j.stroke()}}
    if(!still)SPH.raf=requestAnimationFrame(frame)};
  SPH.raf=requestAnimationFrame(frame)}
