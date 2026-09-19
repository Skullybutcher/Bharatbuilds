/* ProcessPatch UI logic — plain script, no modules, no bundler.
   Global function names are part of the UI contract (see DESIGN.md) and must
   stay stable: go, renderTabs, render, runBuild, cloudRun, submitPolicy,
   loadPolicyFile, toggleJudge, judgeShow, revDecide, patchDecide, activate,
   replay, boundaryX, drill, drawer, closedrawer, openBuild, checkPortal,
   ingestTrace, registerProc, createWs, buildAgainst, authToggle,
   authMaybeExchange, authFetchCfg, esc, get, post. */
let API='http://localhost:8000', BUILD=null, BENCH=null, HISTORY=[], CANDIDATE=null, EXECArn=null, JUDGE=false, JSTEP=0;
/* Theme: light (paper — the ledger default) unless stored dark or OS dark. */
function applyTheme(t){if(t==='light'||t==='dark'||t==='lab'){if(t==='light'){document.documentElement.removeAttribute('data-theme');}else{document.documentElement.setAttribute('data-theme',t);}}else{document.documentElement.removeAttribute('data-theme');}
 const b=document.getElementById('themeBtn');if(b){const ico={light:'ph-moon',dark:'ph-sun',lab:'ph-flask'}[t]||'ph-moon';const lbl={light:'Switch to graphite night theme',dark:'Switch to lab theme',lab:'Switch to paper light theme'}[t]||'Toggle theme';b.innerHTML='<i class="ph '+ico+'" aria-hidden="true"></i>';b.title=lbl;b.setAttribute('aria-label',lbl);}}
function toggleTheme(){const cur=document.documentElement.getAttribute('data-theme')||'light';
 const next={light:'dark',dark:'lab',lab:'light'}[cur]||'light';applyTheme(next);try{localStorage.setItem('pp_theme',next);}catch(e){}}
try{const t=localStorage.getItem('pp_theme')||'lab';applyTheme(t);}catch(e){}
try{if(window.PROCESSPATCH_API){API=window.PROCESSPATCH_API;}}catch(e){}
const TABS=['Overview','Impact','Witnesses','Procedure','Patch','Tests','Approval','Traces','Benchmarks','Builds'];
let active='Overview';
function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');}
const api=()=>{const el=document.getElementById('apiBase');if(el&&!el.value)el.value=API;return (el&&el.value||API).replace(/\/$/,'');};
/* ---------- auth (Cognito hosted UI + PKCE; inert when unset / local dev) ---------- */
let AUTHCFG=window.PROCESSPATCH_AUTH||null;
const AUTH={user:null,id:null,access:null};
async function authFetchCfg(){if(AUTHCFG&&AUTHCFG.clientId)return;try{const c=await get('/auth/config');if(c&&c.enabled){AUTHCFG={clientId:c.client_id,domain:c.domain,redirectUri:location.origin+'/'};}}catch(e){}}
function authCfgOk(){return !!(AUTHCFG&&AUTHCFG.clientId&&AUTHCFG.redirectUri&&AUTHCFG.domain);}
function authClaims(tok){if(!tok)return null;try{const p=JSON.parse(atob(tok.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));const gs=p['cognito:groups']||[];return {email:p.email||p['cognito:username']||p.sub,groups:gs,role:gs.includes('pp-admins')?'admin':(gs.includes('pp-reviewers')?'reviewer':'readonly')};}catch(e){return null;}}
function authSave(){try{localStorage.setItem('pp_tokens',JSON.stringify({id:AUTH.id,access:AUTH.access}));}catch(e){}}
function authLoad(){try{const t=JSON.parse(localStorage.getItem('pp_tokens')||'null');if(t){AUTH.id=t.id;AUTH.access=t.access;AUTH.user=authClaims(t.id||t.access||'');}}catch(e){}}
function authHeaders(){return (AUTH.access&&authCfgOk())?{'Authorization':'Bearer '+AUTH.access}:{};}
function authReviewer(){return AUTH.user?{reviewer_id:AUTH.user.email,display_name:AUTH.user.email}:{reviewer_id:'USR-001',display_name:'Demo Reviewer'};}
function b64url(buf){return btoa(String.fromCharCode.apply(null,new Uint8Array(buf))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
async function authToggle(){
 if(AUTH.user){AUTH.id=null;AUTH.access=null;AUTH.user=null;try{localStorage.removeItem('pp_tokens');}catch(e){}renderTabs();render();return;}
 if(!authCfgOk()){alert('Auth not configured (window.PROCESSPATCH_AUTH). Local dev runs with auth off.');return;}
 const verifier=b64url(crypto.getRandomValues(new Uint8Array(32)));
 sessionStorage.setItem('pp_pkce',verifier);
 location.href='https://'+AUTHCFG.domain+'/oauth2/authorize?response_type=code&client_id='+encodeURIComponent(AUTHCFG.clientId)+'&redirect_uri='+encodeURIComponent(AUTHCFG.redirectUri)+'&scope=openid+email&state='+b64url(crypto.getRandomValues(new Uint8Array(16)));
}
async function authMaybeExchange(){
 const q=new URLSearchParams(location.search);const code=q.get('code');
 if(!code||!authCfgOk())return;
 const body=new URLSearchParams({grant_type:'authorization_code',client_id:AUTHCFG.clientId,code:code,redirect_uri:AUTHCFG.redirectUri,code_verifier:sessionStorage.getItem('pp_pkce')||''});
 try{const r=await fetch('https://'+AUTHCFG.domain+'/oauth2/token',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:body});const t=await r.json();AUTH.id=t.id_token||null;AUTH.access=t.access_token||null;AUTH.user=authClaims(AUTH.id||AUTH.access||'');authSave();}catch(e){}
 history.replaceState({},'',location.pathname);
}
async function get(p){const r=await fetch(api()+p,{headers:authHeaders()});if(r.status===401){alert('Sign-in required — use Sign in (top right).');throw new Error('401 unauthorized');}if(!r.ok)throw new Error('GET '+p+' -> '+r.status);return r.json();}
async function post(p,b){const r=await fetch(api()+p,{method:'POST',headers:{'Content-Type':'application/json',...authHeaders()},body:JSON.stringify(b||{})});if(r.status===401){alert('Sign-in required — use Sign in (top right).');}let d=null;try{d=await r.json();}catch(e){}return {code:r.status,data:d};}
function setView(h){document.getElementById('view').innerHTML=h;}
function loading(msg){setView('<div class="card"><div class="loading" role="status">'+esc(msg||'Loading…')+'<span class="skel"></span><span class="skel"></span></div></div>');}
function showErr(e){setView('<div class="card"><div class="err" role="alert">Request failed: '+esc(e.message||e)+'<br/><small>Start the API with <span class="mono">python -m services.api.server</span>.</small></div></div>');}
const NAV_ICONS={Overview:'graph',Impact:'crosshair',Witnesses:'fingerprint',Procedure:'flow-arrow',Patch:'git-diff',Tests:'check-square',Approval:'seal-check',Traces:'radioactive',Benchmarks:'chart-bar',Builds:'stack'};
function renderTabs(){const t=document.getElementById('tabs');t.innerHTML='<div class="sec">Build</div>'+TABS.map(x=>'<button class="nav-item'+(x===active?' active':'')+'" '+(x===active?'aria-current="page"':'')+' onclick="go(\''+x+'\')"><i class="ph ph-'+(NAV_ICONS[x]||'square')+'" aria-hidden="true"></i>'+esc(x)+'</button>').join('')+'<div class="sec">AWS</div><div class="aws-chip" id="awsBox"></div>';const ab=document.getElementById('awsBox');if(ab)ab.innerHTML='<b>Cloud execution</b>'+(EXECArn?('running · '+esc(EXECArn.slice(0,34))+'…'):'none yet — use Cloud (top right)');const aub=document.getElementById('authBtn');if(aub)aub.textContent=AUTH.user?('Sign out · '+AUTH.user.role):'Sign in';}
function go(x){active=x;renderTabs();render();}
function badge(){const b=document.getElementById('buildBadge');if(!BUILD){b.textContent='no build yet';b.className='badge';return;}const n=(BUILD.witnesses||[]).length;const st=BUILD.status||'?';b.textContent=BUILD.build_id+' · '+st+' · '+n+' witnesses';b.className='badge '+(st==='PATCH_VALIDATED'||st==='PATCH_ACTIVE'?'pass':(n?'fail':'warn'));}
function trust(t){if(t==='FIXTURE')return '<span class="tag info"><i class="ph ph-flask" aria-hidden="true"></i>Fixture · hand-authored gold Rule IR</span>';if(t==='DETERMINISTIC_PARSER')return '<span class="tag info"><i class="ph ph-brackets-curly" aria-hidden="true"></i>Deterministic parser · bounded language</span>';if(t==='BEDROCK_CANDIDATE')return '<span class="tag warn"><i class="ph ph-robot" aria-hidden="true"></i>Model candidate · requires human review</span>';return t==='VERIFIED'?'<span class="tag fail"><i class="ph ph-fingerprint" aria-hidden="true"></i>Verified · witness reproduces</span>':t==='VALIDATED'?'<span class="tag pass"><i class="ph ph-seal-check" aria-hidden="true"></i>Validated · patch passed checks</span>':t==='HUMAN'?'<span class="tag warn"><i class="ph ph-user-check" aria-hidden="true"></i>Human-approved</span>':'<span class="tag">'+esc(t)+'</span>';}
function backendBadge(){const b=(BUILD&&BUILD.extraction_backend)||'fixture';if((b||'').startsWith('bedrock:'))return trust('BEDROCK_CANDIDATE');return trust(b==='fixture'?'FIXTURE':'DETERMINISTIC_PARSER');}
/* Gate spine — the pipeline as a connected tracker. Stages map to real
   backend state only (status/validation/witness counts); never decorative.
   The first incomplete stage is "now"; every earlier one is "done". */
function gateSpine(){const w=(BUILD&&BUILD.witnesses||[]).length;const v=(BUILD&&BUILD.validation)||{};const st=(BUILD&&BUILD.status)||'';
 const stages=[['Compile','policy → Rule IR',!!BUILD],
  ['Witness','verified failing case'+(w===1?'':'s'),w>0],
  ['Validate','regression suite',v.status==='PATCH_VALIDATED'],
  ['Approve','human decision, hash-bound',(BUILD&&BUILD.review_state==='APPROVED')||st==='PATCH_ACTIVE'],
  ['Activate','procedure version live',st==='PATCH_ACTIVE']];
 let nowIdx=stages.findIndex(s=>!s[2]);if(nowIdx<0)nowIdx=stages.length;
 return '<ol class="spine" aria-label="Pipeline stage">'+stages.map((s,i)=>'<li class="'+(s[2]?'done':(i===nowIdx?'now':''))+'"><span class="dot" aria-hidden="true">'+(s[2]?'✓':(i===nowIdx?'●':''))+'</span><span class="st">'+s[0]+'</span><span class="sd">'+s[1]+'</span></li>').join('')+'</ol>';}
function render(){badge();if(!BUILD){setView('<div class="card hero"><div>'
+'<h1>A policy changed.<br/>Which procedure steps are wrong now?</h1>'
+'<p class="lead">Compile the amendment, prove each failure with a verified witness, ship a hash-bound patch — gated by human approval.</p>'
+'<div class="hero-cta"><button class="btn lg" onclick="runBuild()">Compile Amendment</button><small>Local deterministic pipeline · no sign-in needed</small></div>'
+gateSpine()+'</div>'
+'<div><div class="editor"><div class="ed-head"><b>Policy input</b><small>paste text or upload a .md file</small></div>'
+'<textarea id="policyText" rows="7" placeholder="Paste policy text, drag a .md file here, or use the file picker below"></textarea>'
+'<div class="ed-foot"><input type="file" accept=".md,.txt" onchange="loadPolicyFile(this)"/><button class="btn sm" onclick="submitPolicy()">Compile pasted policy</button><small>Unparseable input stays pending at review — fail-closed.</small></div></div></div>'
+dashHtml());dashFill();dragPolicy();return;}
/* Drag-and-drop policy files onto the editor (functional affordance, not decoration). */
function dragPolicy(){const ta=document.getElementById('policyText');if(!ta)return;
 ['dragover','dragenter'].forEach(ev=>ta.addEventListener(ev,e=>{e.preventDefault();ta.classList.add('drag');}));
 ['dragleave','drop'].forEach(ev=>ta.addEventListener(ev,e=>{e.preventDefault();ta.classList.remove('drag');}));
 ta.addEventListener('drop',e=>{const f=e.dataTransfer&&e.dataTransfer.files&&e.dataTransfer.files[0];if(f)readPolicyFile(f);});}
function readPolicyFile(f){const r=new FileReader();r.onload=()=>{const ta=document.getElementById('policyText');if(ta){ta.value=String(r.result||'');ta.focus();}};r.readAsText(f);}
try{({Overview:vOverview,Impact:vImpact,Witnesses:vWit,Procedure:vProc,Patch:vPatch,Tests:vTests,Approval:vApproval,Traces:vTraces,Benchmarks:vBench,Builds:vHist})[active]();}catch(e){showErr(e);}}
/* ---------- actions ---------- */
async function runBuild(){const d=document.getElementById('domain').value;loading('Compiling amendment (deterministic pipeline)…');try{BUILD=await get('/demo/canonical?domain='+d);}catch(e){showErr(e);return;}drilled=null;CANDIDATE=null;EXECArn=null;active='Overview';renderTabs();render();loadHistory();}
async function refreshBuild(){if(BUILD){try{BUILD=await get('/builds/'+BUILD.build_id);}catch(e){}render();}}
async function loadHistory(){try{HISTORY=(await get('/builds')).builds||[];}catch(e){}}
/* No-build dashboard modules — real stored data only, never decoration.
   Rendered as empty containers; filled asynchronously after setView. */
function dashHtml(){return '<div class="activity">'
+'<div class="mini"><div class="m-head"><b>Recent builds</b><i class="ph ph-stack" aria-hidden="true"></i></div><div id="dashBuilds"><span class="skel"></span></div></div>'
+'<div class="mini"><div class="m-head"><b>Runtime traces</b><i class="ph ph-radioactive" aria-hidden="true"></i></div><div id="dashTraces"><span class="skel"></span></div></div>'
+'<div class="mini"><div class="m-head"><b>Procedure versions</b><i class="ph ph-flow-arrow" aria-hidden="true"></i></div><div id="dashProcs"><span class="skel"></span></div></div>'
+'</div>';}
function dashFill(){dashOne('dashBuilds','/builds','build_id',d=>d.builds||[],id=>"openBuild('"+id+"')");
 dashOne('dashTraces','/traces','trace_id',d=>d.traces||[],()=>"go('Traces')");
 dashOne('dashProcs','/procedures','procedure_version_id',d=>d.versions||[],()=>"go('Builds')");}
async function dashOne(elId,endpoint,idKey,pluck,openFn){const el=document.getElementById(elId);if(!el)return;
 try{const items=pluck(await get(endpoint)).slice(0,4);
 el.innerHTML=items.length?items.map(x=>'<div class="row" onclick="'+openFn(String(x[idKey]))+'"><span class="r-id">'+esc(x[idKey])+'</span><span class="r-meta">'+esc(x.status||x.source||x.workflow_id||'')+'</span></div>').join(''):'<p class="mut">nothing stored yet</p>';
 }catch(e){el.innerHTML='<p class="mut">unavailable</p>';}}
async function cloudRun(){const d=document.getElementById('domain').value;loading('Registering DRAFT → starting Step Functions execution…');try{
const b=await post('/builds',{domain:d,defer:true});const ex=await post('/builds/'+b.data.build_id+'/execute',{});EXECArn=ex.data.executionArn;
setView('<div class="card"><div class="card-head"><h3>Cloud execution</h3></div><div class="mono">'+esc(EXECArn)+'\nstatus: '+esc(ex.data.status)+'\n'+esc(ex.data.note||'')+'</div><div id="execPoll" class="mono">polling…</div></div>');
for(let i=0;i<10;i++){await new Promise(r=>setTimeout(r,3000));try{const s=await get('/executions/'+encodeURIComponent(EXECArn));const el=document.getElementById('execPoll');if(el)el.textContent='status: '+s.status;if(s.status!=='RUNNING')break;}catch(e){break;}}
BUILD=await get('/builds/'+ex.data.build_id);}catch(e){showErr(e);return;}drilled=null;CANDIDATE=null;active='Overview';renderTabs();render();loadHistory();}
async function submitPolicy(){const t=document.getElementById('policyText').value;if(!t.trim()){alert('paste policy text first');return;}const d=document.getElementById('domain').value;loading('Extracting + compiling pasted policy…');const r=await post('/builds',{domain:d,policy_text:t,policy_version_id:'POLICY-UPLOAD'});
if(r.data.status==='NEEDS_REVIEW'||r.data.status==='CONFLICT'||r.data.status==='EXTRACTION_UNAVAILABLE'){BUILD=r.data;active='Approval';renderTabs();render();alert('Extraction needs review: '+r.data.status+' — see Gate 1.');return;}
BUILD=r.data;drilled=null;CANDIDATE=null;active='Overview';renderTabs();render();}
function loadPolicyFile(inp){const f=inp.files[0];if(f)readPolicyFile(f);}
function isCloud(){return EXECArn&&!EXECArn.startsWith('local:');}
async function checkPortal(p){const g=id=>{const el=document.getElementById(id);return el?el.value:'';};const q='cgpa='+encodeURIComponent(g('cgpa')||7.8)+'&amount='+encodeURIComponent(g('amt')||40000)+'&patched='+(p?1:0)+'&domain='+document.getElementById('domain').value;const j=await get('/portal?'+q);
document.getElementById('portalOut').textContent='Expected: eligible='+j.expected.eligible+' required='+JSON.stringify(j.expected.required)+'\nActual:   eligible='+j.actual.eligible+' required='+JSON.stringify(j.actual.required)+'\n'+((j.expected.eligible!==j.actual.eligible||JSON.stringify(j.expected.required)!==JSON.stringify(j.actual.required))?'DISAGREEMENT — PROCEDURAL DRIFT CONFIRMED':'agree');}
/* ---------- Overview ---------- */
function heroCase(){const w=(BUILD.witnesses||[])[0];if(!w)return null;const c=w.case;const numKey=Object.keys(c).find(k=>typeof c[k]==='number'&&k!=='year'&&k!=='backlogs')||'cgpa';return {w,numKey};}
function vOverview(){const w=BUILD.witnesses||[];const v=BUILD.validation||{failed:'—',total:'—',status:BUILD.status};const h=heroCase();
const hero=h?'<div class="card"><p class="kicker">Policy × person × procedure</p><div class="evidence-grid">'
+'<div class="ecol"><p class="kicker">Policy delta</p><div class="mono">'+esc(JSON.stringify((BUILD.semantic_delta||{}).notes||[]).slice(0,160)||(BUILD.semantic_delta||{}).type||'')+'</div></div>'
+'<div class="ecol"><p class="kicker">Representative case</p><div class="mono">'+esc(h.numKey)+' = '+esc(h.w.case[h.numKey])+'</div><div>Expected: <b>'+esc(JSON.stringify(h.w.expected.eligible!=null?h.w.expected.eligible:h.w.expected))+'</b><br/>Actual: <b>'+esc(JSON.stringify(h.w.actual.eligible!=null?h.w.actual.eligible:h.w.actual))+'</b></div></div>'
+'<div class="ecol"><p class="kicker">Stale location</p><div class="mono">'+esc((BUILD.faults||[]).map(f=>(f.affected_nodes||[]).join(',')).join('; ').slice(0,160))+'</div></div></div>'
+'<div class="result-line bad" role="status">Result: DISAGREEMENT — '+esc(h.w.kind)+'</div></div>':'<div class="card"><div class="result-line ok" role="status">Result: no drift — procedure matches the active rules.</div></div>';
setView('<div class="card"><p class="kicker">Build status</p><div class="card-head"><h2>Research Grant Workflow · '+esc(BUILD.build_id)+'</h2><span class="badge '+(w.length?'fail':'pass')+'">'+esc(BUILD.status||'?')+'</span></div>'
+'<p>'+esc((BUILD.semantic_delta||{}).type||'no compiled delta yet')+' · '+w.length+' witnesses · '+(BUILD.faults||[]).length+' fault regions · '+esc(v.failed)+' failing checks</p>'
+'<p>Extraction: '+backendBadge()+' <span class="tag">Review: '+esc(BUILD.review_state||'—')+'</span>'+(EXECArn?'<span class="tag">exec '+esc(EXECArn.slice(0,20))+'…</span>':'')+'</p>'
+'<div class="cols4">'+[['Semantic changes',(BUILD.impact||{}).semantic_changes||((BUILD.semantic_delta||{}).affected_rule_ids||[]).length||'—'],['Verified witnesses',w.length],['Affected nodes',((BUILD.impact||{}).artifacts||{}).nodes_affected||'—'],['Patch checks',(v.passed||'—')+'/'+(v.total||'—')]].map(a=>'<div class="card flat stat"><div class="num">'+esc(a[1])+'</div><div class="lbl">'+esc(a[0])+'</div></div>').join('')+'</div>'
+'<div class="pipeline-strip" aria-label="Pipeline">Policy change <span class="sep">→</span> Compile <span class="sep">→</span> Witness <span class="sep">→</span> Localized patch <span class="sep">→</span> Regression tests <span class="sep">→</span> Validated procedure <span class="sep">→</span> <b style="color:var(--txt)">Human approval</b></div></div>'
+'<div class="card">'+gateSpine()+'</div>'
+hero+'<div class="card"><div class="card-head"><h3>Synthetic portal — driven by procedure JSON</h3></div><label class="field">CGPA <input id="cgpa" value="7.80"/></label> <label class="field">Amount <input id="amt" value="40000"/></label> '
+'<button class="btn" onclick="checkPortal(false)">Check (current portal)</button><button class="btn ghost" onclick="checkPortal(true)">Check (patched preview)</button><div id="portalOut" class="mono" style="margin-top:16px" role="status" aria-live="polite"></div></div>'
+'<div class="card"><div class="card-head"><h3>Policy input</h3></div><label class="field" for="policyText">Policy text</label><textarea id="policyText" rows="4" placeholder="Paste policy text, or upload a .md file"></textarea><br/><input type="file" accept=".md,.txt" onchange="loadPolicyFile(this)"/> <button class="btn" onclick="submitPolicy()">Compile pasted policy</button> <small>Unparseable or qualified input stays PENDING at Gate 1.</small></div>');
fillCoverage();}
/* ---------- Impact ---------- */
let drilled=null;
async function vImpact(){const im=BUILD.impact||{};const b=im.behavioral||{},tc=im.test_cohort||{},v=im.verification||{};const max=Math.max(1,...Object.values(b));
const rows=Object.entries(b).map(([k,n])=>'<tr><td><a href="#" onclick="drill(\''+esc(k)+'\');return false;">'+esc(k)+' ('+esc(n)+')</a></td><td><div class="bar"><div style="width:'+Math.round(100*n/max)+'%;background:var(--fail-strong)"></div></div></td></tr>').join('');
const tcrows=[['unchanged',tc.unchanged,'var(--grey,#6b7280)'],['shorter journeys',tc.shorter_journeys,'var(--pass)'],['newly eligible',tc.newly_eligible,'var(--accent)'],['longer journeys',tc.longer_journeys,'var(--warn-strong)']].map(a=>'<div>'+esc(a[0])+': <b>'+esc(a[1]||0)+'</b><div class="bar"><div style="width:'+Math.round(100*(a[1]||0)/Math.max(1,tc.cohort_size))+'%;background:'+a[2]+'"></div></div></div>').join('');
setView('<div class="card"><p class="kicker">Impact</p><div class="card-head"><h3>What changed, where it propagated, who is affected</h3></div>'
+'<div class="cols"><div class="card flat"><p class="kicker">What changed</p><div class="mono">'+esc((im.semantic_breakdown||{}).delta_type||'')+'</div><div class="mono">rules: '+esc(((im.artifacts||{}).affected_rules||[]).join(', '))+'</div></div>'
+'<div class="card flat"><p class="kicker">Blast radius</p><div class="mono">workflows: '+esc((im.artifacts||{}).workflows_affected)+' · nodes: '+esc((im.artifacts||{}).nodes_affected)+'\n'+esc(((im.artifacts||{}).affected_nodes||[]).join(', '))+'\nfields: '+esc(((im.artifacts||{}).fields_affected||[]).join(', ')||'—')+'</div></div>'
+'<div class="card flat"><p class="kicker">Human impact</p><div class="mono">Generated test cohort (synthetic, n='+esc(tc.cohort_size)+')</div>'+tcrows+'<small>Never imply population prevalence from synthetic cases. Behavioral counts are representative verified witnesses, not headcounts.</small></div></div>'
+'<div class="cols2"><div class="card flat"><p class="kicker">Behavioral counts (select to drill down)</p><table><thead><tr><th>kind</th><th>share</th></tr></thead><tbody>'+rows+'</tbody></table><div id="drill" class="mono" role="status"></div></div>'
+'<div class="card flat" id="covCard"><p class="kicker">Witness coverage of the blast radius</p><div class="mono" role="status"><span class="skel"></span></div><small class="mut">covered = a verified witness exercises this node/field — nothing else counts</small></div>'
+'<div class="card flat"><p class="kicker">Regression + trust</p><div class="mono">Before: '+((v.tests_before||{}).failed)+' failing\nAfter: '+((v.tests_after||{}).failed||0)+' failing / '+((v.tests_after||{}).total||0)+'\nprovenance: '+esc(v.provenance_coverage)+'\nRule review: '+esc(BUILD.review_state)+'\nMachine: '+esc((v.tests_after?'COMPLETE':'—'))+'\nHuman: '+esc(((im.approval||{}).human_status||'AWAITING_APPROVAL'))+'</div></div></div></div>');}
async function fillCoverage(){const el=document.getElementById('covCard');if(!el)return;let c=null;try{c=await get('/builds/'+BUILD.build_id+'/coverage');}catch(e){el.querySelector('.mono').textContent='coverage unavailable';return;}
const mk=(dim,label)=>{const d=c[dim]||{};if(!d.total)return '<p class="mut">no '+label+' in this change\'s blast radius</p>';
const pct=Math.round((d.pct||0)*100);const tone=pct>=100?'var(--pass)':pct>=50?'var(--warn-strong)':'var(--fail-strong)';
return '<div class="bar" style="margin:6px 0 10px"><div style="width:'+pct+'%;background:'+tone+'"></div></div><small>'+d.covered+' of '+d.total+' '+label+' covered ('+pct+'%)</small>'
+(pct<100?'<div class="mono" style="margin-top:6px">uncovered: '+esc(d.rows.filter(r=>!r.covered).map(r=>r.node_id||r.field).join(', '))+'</div>':'');};
el.querySelector('.mono').innerHTML='<b>Nodes</b>'+mk('nodes','affected node')+'<b>Rule fields</b>'+mk('fields','affected field');}
function drill(kind){const map={wrong_rejections:'wrong_rejection',wrong_acceptances:'wrong_acceptance',unnecessary_burdens:'unnecessary_burden',missing_safeguards:'missing_safeguard',wrong_orderings:'wrong_journey',deadline_mismatches:'deadline_mismatch',prohibition_breaches:'prohibition_breach'};const k=map[kind];const list=(BUILD.witnesses||[]).filter(w=>w.kind===k);
document.getElementById('drill').textContent=list.map(w=>w.witness_id+' '+JSON.stringify(w.case)).join('\n')||'none';}
/* ---------- Witnesses (debugger) ---------- */
function vWit(){const w=BUILD.witnesses||[];if(!w.length){setView('<div class="card"><div class="empty" role="status"><i class="ph ph-fingerprint e-ico" aria-hidden="true"></i><b>No witnesses</b> — semantics equivalent. Compile an amendment that changes behavior to see verified failing cases here.</div></div>');return;}
setView('<div class="card"><p class="kicker">Each witness is a verified failing case — one person per failure mode</p></div>'+w.map((x,i)=>{const rows=Object.entries(x.case).map(([k,v])=>'<tr><td>'+esc(k)+'</td><td class="num">'+esc(v)+'</td></tr>').join('');
return '<div class="card casefile"><div class="cf-head"><p class="kicker">Witness '+(i+1)+' of '+w.length+'</p><span class="tag fail"><i class="ph ph-fingerprint" aria-hidden="true"></i>Verified · reproduces</span></div><div class="card-head"><h3>'+esc(x.witness_id)+' · '+esc(x.kind)+'</h3></div>'
+'<p class="mut">Who gets the wrong outcome? One representative case per failure mode.</p>'
+'<div class="cols2"><div><p class="kicker">Applicant</p><table><thead><tr><th>field</th><th class="num">value</th></tr></thead><tbody>'+rows+'</tbody></table></div>'
+'<div><p class="kicker">Expected vs actual path</p><div class="cols2"><div><div class="mut">EXPECTED</div><div class="mono">'+esc(x.trace_expected.join('\n'))+'</div></div><div><div class="mut">ACTUAL</div><div class="mono">'+esc(x.trace_actual.join('\n'))+'</div></div></div></div></div>'
+'<div id="bx-'+i+'" class="mono" role="status"></div><button class="btn ghost sm" onclick="replay(\''+esc(x.witness_id)+'\')">Replay witness</button> <button class="btn ghost sm" onclick="boundaryX('+i+')">Boundary explorer</button><div id="rp-'+esc(x.witness_id)+'" class="mono" role="status"></div></div>';}).join(''));}
async function replay(wid){const j=await post('/builds/'+BUILD.build_id+'/witnesses/'+wid+'/replay',{});document.getElementById('rp-'+wid).textContent='after-patch eligible='+j.data.actual_after.eligible+' required='+JSON.stringify(j.data.actual_after.required);}
async function boundaryX(i){const x=BUILD.witnesses[i];const nums=Object.entries(x.case).filter(([k,v])=>typeof v==='number');if(!nums.length){document.getElementById('bx-'+i).textContent='no numeric fields';return;}
let out='field | value | expected | actual\n';
for(const [f,v] of nums){for(const d of [-0.02,-0.01,0,0.01,0.02]){const val=Math.round((v+d)*100)/100;const q={...x.case,[f]:val};const qs='cgpa='+encodeURIComponent(q.cgpa??7.8)+'&amount='+encodeURIComponent(q.amount??40000)+'&patched=0&domain='+document.getElementById('domain').value;try{const j=await get('/portal?'+qs);out+=f+' '+val+' elig='+j.expected.eligible+' elig='+j.actual.eligible+'\n';}catch(e){}}}
document.getElementById('bx-'+i).textContent=out;}
/* ---------- Procedure (SVG graph + drawer) ---------- */
function nodeStatus(n,beforeIds,afterIds,changedIds,faultIds){if(!beforeIds.has(n.node_id))return 'added';if(!afterIds.has(n.node_id))return 'removed';if(changedIds.has(n.node_id))return 'changed';if(faultIds.has(n.node_id))return 'stale';return 'same';}
function vProc(){const showPatched=window._showPatched!==false;const wf=showPatched?(BUILD.patched_workflow||BUILD.procedure):BUILD.procedure;if(!wf){setView('<div class="card"><div class="empty" role="status">No procedure on this build.</div></div>');return;}
const before=BUILD.procedure||{nodes:[]};const after=BUILD.patched_workflow||before;
const bmap={};before.nodes.forEach(n=>bmap[n.node_id]=n);const amap={};after.nodes.forEach(n=>amap[n.node_id]=n);
const changed=new Set();Object.keys(amap).forEach(id=>{if(bmap[id]&&JSON.stringify(bmap[id].implementation)!==JSON.stringify(amap[id].implementation))changed.add(id);});
const fault=new Set();(BUILD.faults||[]).forEach(f=>(f.affected_nodes||[]).forEach(n=>fault.add(n)));
const indeg={};wf.nodes.forEach(n=>indeg[n.node_id]=0);(wf.edges||[]).forEach(e=>{if(indeg[e.to]!=null)indeg[e.to]++;});
const levels={};let frontier=wf.nodes.filter(n=>indeg[n.node_id]===0).map(n=>n.node_id);let lv=0;const seen=new Set();
while(frontier.length&&lv<12){const next=[];frontier.forEach(id=>{if(seen.has(id))return;seen.add(id);levels[id]=lv;(wf.edges||[]).filter(e=>e.from===id).forEach(e=>next.push(e.to));});frontier=next;lv++;}
wf.nodes.forEach(n=>{if(!(n.node_id in levels))levels[n.node_id]=lv;});
const W=1100,rowH=86,colW=200;const byLv={};Object.entries(levels).forEach(([id,l])=>{(byLv[l]=byLv[l]||[]).push(id);});
let svg='<svg class="graph" width="100%" viewBox="0 0 '+W+' '+Math.max(140,(lv+1)*rowH)+'" role="img" aria-label="Procedure graph">';
const pos={};Object.entries(byLv).forEach(([l,ids])=>{ids.forEach((id,i)=>{const x=40+i*Math.min(colW,(W-80)/Math.max(1,ids.length));const y=30+Number(l)*rowH;pos[id]={x,y};});});
(wf.edges||[]).forEach(e=>{const a=pos[e.from],b=pos[e.to];if(!a||!b)return;svg+='<line x1="'+(a.x+70)+'" y1="'+(a.y+22)+'" x2="'+(b.x+70)+'" y2="'+(b.y-4)+'" stroke="#3d4a60" stroke-width="2" marker-end="url(#ah)"/>';});
const col={added:'#16a34a',removed:'#dc2626',changed:'#d97706',stale:'#dc2626',same:'#4b5563'};
wf.nodes.forEach(n=>{const p=pos[n.node_id];const st=nodeStatus(n,new Set(Object.keys(bmap)),new Set(Object.keys(amap)),changed,fault);
svg+='<g class="node" tabindex="0" role="button" aria-label="'+esc(n.label)+'" onclick="drawer(\''+esc(n.node_id)+'\')" onkeydown="if(event.key===\'Enter\'||event.key===\' \'){drawer(\''+esc(n.node_id)+'\')}"><rect x="'+p.x+'" y="'+(p.y-4)+'" width="140" height="30" rx="8" fill="#12161f" stroke="'+col[st]+'" stroke-width="2.5"/><text x="'+(p.x+70)+'" y="'+(p.y+15)+'" text-anchor="middle">'+esc(n.label.slice(0,20))+'</text></g>';});
svg+='<defs><marker id="ah" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8" fill="none" stroke="#3d4a60" stroke-width="1.5"/></marker></defs></svg>';
setView('<div class="card"><p class="kicker">Procedure '+(showPatched?'(patched preview)':'(stale)')+' · '+esc(wf.procedure_version_id||'')+'</p><div class="card-head"><h3>Procedure graph</h3><span><button class="btn ghost sm" onclick="window._showPatched=false;render()">Before</button> <button class="btn ghost sm" onclick="window._showPatched=true;render()">After</button></span></div>'
+'<div class="legend" aria-label="Node status legend"><span><i style="background:#4b5563"></i>unchanged</span><span><i style="background:#dc2626"></i>stale</span><span><i style="background:#16a34a"></i>added</span><span><i style="background:#d97706"></i>changed</span></div>'+svg
+'<table><thead><tr><th>node</th><th>config</th><th>provenance</th></tr></thead><tbody>'+wf.nodes.map(n=>'<tr><td>'+esc(n.node_id)+'<br/><small>'+esc(n.label)+'</small></td><td class="mono">'+esc(JSON.stringify(n.implementation))+'</td><td class="mono">'+esc(JSON.stringify(n.provenance_links))+'</td></tr>').join('')+'</tbody></table></div>');}
function drawer(nid){const wf=BUILD.patched_workflow||BUILD.procedure;const n=(wf.nodes||[]).find(x=>x.node_id===nid);if(!n)return;
const rules={};(BUILD.new_rules||[]).forEach(r=>rules[r.rule_id]=r);
const chain=(n.provenance_links||[]).map(l=>{const r=rules[l.target]||{};const p=r.provenance||{};return '<div><span class="tag">WHY THIS STEP EXISTS</span><div class="mono">'+esc(l.target)+'\n'+esc(p.source_text||'')+'\nPolicy '+esc(p.policy_version_id||'')+' §'+esc(p.section||'')+'</div></div>';}).join('')||'<div class="mut">structural node</div>';
const wit=(BUILD.witnesses||[]).filter(w=>JSON.stringify(w).includes(nid)).map(w=>w.witness_id).join(', ');
const ops=((BUILD.patch||{}).operations||[]).filter(o=>o.node_id===nid);
document.getElementById('drawerRoot').innerHTML='<div class="overlay" onclick="closedrawer()"></div><div class="drawer" role="dialog" aria-label="'+esc(n.label)+'"><p class="kicker">Node detail</p><h3>'+esc(n.label)+'</h3><div class="mono">'+esc(n.node_id)+'</div>'+chain+'<p><b>Witnesses touching this node:</b> '+esc(wit||'—')+'</p><p><b>Patch ops:</b></p><div class="mono">'+esc(JSON.stringify(ops,null,2))+'</div><button class="btn ghost" onclick="closedrawer()">Close</button></div>';}
function closedrawer(){document.getElementById('drawerRoot').innerHTML='';}
/* ---------- Patch (git diff) ---------- */
function vPatch(){const pt=BUILD.patch||{};const ops=pt.operations||[];
const blocks=ops.map(o=>{let body='';if(o.op==='CHANGE_CONDITION')body='- '+esc(o.field||'condition')+': '+esc(JSON.stringify(o.old))+'\n+ '+esc(o.field||'condition')+': '+esc(JSON.stringify(o.new));else if(o.op==='CHANGE_REQUIRED_FLAG')body='- required: '+esc(JSON.stringify((o.old||{}).required))+'\n+ required: '+esc(JSON.stringify((o.new||{}).required))+((o.new&&o.new.required_condition)?'\n+ required_if: '+esc(JSON.stringify(o.new.required_condition)):'');else body=esc(o.op)+' '+esc(o.node_id||o.from||'');
return '<div class="card flat"><p class="kicker">'+esc(o.node_id||o.op)+'</p><div class="mono">'+body+'\nReason: '+esc(o.rationale||'—')+'</div></div>';}).join('');
setView('<div class="card"><p class="kicker">Candidate patch '+esc(pt.patch_id||'')+'</p><div class="card-head"><h3>'+ops.length+' workflow edits · cost '+esc(pt.cost)+' · <span class="tag pass">VALIDATED</span></h3></div><p class="mut">'+esc(pt.strategy||'')+'</p>'+(blocks||'<div class="empty" role="status">No operations (semantics already equivalent).</div>')+'</div>');}
/* ---------- Tests (actions style) ---------- */
function vTests(){const v=BUILD.validation||{results:[]};const groups={};(v.results||[]).forEach(r=>{(groups[r.suite]=groups[r.suite]||[]).push(r);});
const names={witness:'Witness replay',boundary:'Boundary behavior',unchanged:'Preservation',integrity:'Workflow integrity',ordering:'Ordering',metamorphic:'Metamorphic',provenance:'Provenance'};
setView('<div class="card"><p class="kicker">Regression</p><div class="card-head"><h3>'+esc(v.passed)+'/'+esc(v.total)+' passing · '+esc(v.status)+'</h3></div><p class="mut">Never COMPLIANCE GUARANTEED. Only VALIDATED_WITHIN_TESTED_MODEL.</p>'+Object.entries(groups).map(([s,rs])=>{const ok=rs.filter(r=>r.pass).length;return '<div class="suite" id="sq-'+esc(s)+'"><button onclick="document.getElementById(\'sq-'+esc(s)+'\').classList.toggle(\'open\')" aria-expanded="false"><span class="verdict '+(ok===rs.length?'p':'f')+'">'+(ok===rs.length?'PASS':'FAIL')+'</span> '+esc(names[s]||s)+' — '+ok+'/'+rs.length+'</button><div class="detail"><table><thead><tr><th>case</th><th>result</th><th>detail</th></tr></thead><tbody>'+rs.map(r=>'<tr><td class="mono">'+esc(JSON.stringify(r.case)).slice(0,120)+'</td><td>'+(r.pass?'PASS':'FAIL')+'</td><td>'+esc(r.detail||'')+'</td></tr>').join('')+'</tbody></table></div></div>';}).join('')+'</div>');}
/* ---------- Approval (protected merge) ---------- */
async function vApproval(){if(!BUILD){setView('<div class="card"><div class="empty" role="status"><i class="ph ph-seal-check e-ico" aria-hidden="true"></i><b>No build selected.</b> Compile an amendment first, then review it here.<br/><br/><button class="btn" onclick="runBuild()">Compile Amendment</button></div></div>');return;}loading('Loading governance state…');let rev,appr,g,log;try{[rev,appr,g,log]=await Promise.all([get('/builds/'+BUILD.build_id+'/rule-reviews'),get('/builds/'+BUILD.build_id+'/approvals'),get('/builds/'+BUILD.build_id+'/guardrails'),get('/builds/'+BUILD.build_id+'/audit')]);}catch(e){showErr(e);return;}
const dis=(g.blockers||[]).length>0;const steps=[['Rule interpretation reviewed','unresolved reviews = 0',(g.checks||{}).unresolved_rule_review===0],['Patch tests pass','VALIDATED_WITHIN_TESTED_MODEL',(g.checks||{}).patch_validation==='VALIDATED_WITHIN_TESTED_MODEL'],['Preservation passed','unchanged behavior preserved',(g.checks||{}).preservation==='PASS'],['Provenance 100%','every node traced to policy',(g.checks||{}).provenance_coverage>=1],['Candidate hash unchanged','no hash blockers',!(g.blockers||[]).some(b=>String(b).includes('hash'))]];
const checkPill=(k,v)=>{const good=v===true||v==='PASS'||v==='VALIDATED_WITHIN_TESTED_MODEL'||(typeof v==='number'&&v>=1);return '<span class="tag '+(good?'pass':'warn')+'">'+esc(k)+': '+esc(String(v))+'</span>';};
setView('<div class="card"><p class="kicker">Merge protection — what exactly am I being asked to accept?</p><div class="card-head"><h3>Approval gates</h3></div>'
+'<ol class="steps">'+steps.map((s,i)=>'<li class="'+(s[2]?'s-ok':'s-bad')+'"><span class="n" aria-hidden="true">'+(s[2]?'✓':'✕')+'</span><span><span class="t">'+esc(s[0])+'</span><br/><span class="d">'+esc(s[1])+'</span></span></li>').join('')+'</ol>'
+'<div class="cols2"><div class="card flat"><p class="kicker">Gate 1 · Rules</p><table><thead><tr><th>rule</th><th>decision</th><th></th></tr></thead><tbody>'+(rev.reviews||[]).map(r=>'<tr><td class="mono">'+esc(r.rule_id)+'</td><td>'+esc(r.decision)+'</td><td><button class="btn ghost sm" onclick="revDecide(\''+esc(r.rule_id)+'\',\'accept\')">Accept</button> <button class="btn ghost sm" onclick="revDecide(\''+esc(r.rule_id)+'\',\'reject\')">Reject</button></td></tr>').join('')+'</tbody></table></div>'
+'<div class="card flat"><p class="kicker">Gate 2 · Patch</p><div>'+Object.entries(g.checks||{}).map(([k,v])=>checkPill(k,v)).join('')+'</div>'+(g.blockers&&g.blockers.length?'<p style="margin-top:8px">'+g.blockers.map(b=>'<span class="tag fail">'+esc(String(b))+'</span>').join('')+'</p>':'<p class="mut" style="margin-top:8px">no blockers</p>')
+'<label class="field">Reviewer <input id="revName" value="Demo Reviewer"/></label> <label class="field">Reason <input id="revReason" value="Matches policy; all checks pass." style="width:240px"/></label><br/>'
+'<button class="btn ok sm" '+(dis?'disabled':'')+' onclick="patchDecide(\'approve\')">Approve candidate</button> <button class="btn danger sm" onclick="patchDecide(\'reject\')">Request changes</button> <button class="btn ghost sm" onclick="patchDecide(\'revision\')">Request revision</button>'
+(dis?'<p><small>Approve disabled by merge protection above.</small></p>':'')+'</div></div>'
+'<div class="cols2"><div class="card flat"><p class="kicker">Gate 3 · Activation</p><p><small>Activates the exact candidate id from approval (hash-verified server-side).</small></p><button class="btn ok sm" onclick="activate()">Activate candidate</button><div id="actOut" class="mono" role="status"></div></div>'
+'<div class="card flat"><p class="kicker">Approvals + audit</p><div class="mono">'+esc(JSON.stringify(appr.approvals))+'\n---\n'+(log.audit||[]).map(e=>new Date(e.ts*1000).toISOString()+' '+esc(e.event)).join('\n')+'</div></div></div>'
+'<div class="card flat"><p class="kicker">Patch certificate</p><div class="mono">'+esc(JSON.stringify(BUILD.certificate))+'</div><div style="margin-top:10px"><button class="btn sm" onclick="downloadBundle()">Download governance bundle</button> <span class="mut">one JSON file: reviews, approvals, guardrails, witnesses, patch, certificate, audit — sha256-sealed</span></div></div></div>');}
async function downloadBundle(){if(!BUILD)return;try{const r=await fetch(api()+'/builds/'+BUILD.build_id+'/governance-bundle',{headers:authHeaders()});let d=null;try{d=await r.json();}catch(e){}
if(!r.ok){alert('Bundle refused: '+((d&&d.error)||('HTTP '+r.status)));return;}
const blob=new Blob([JSON.stringify(d,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=BUILD.build_id+'-governance-bundle.json';document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(a.href);}catch(e){showErr(e);}}
async function revDecide(rid,how){if(isCloud()){await post('/builds/'+BUILD.build_id+'/resume',{gate:'rule_review',decisions:{[rid]:how.toUpperCase()},reviewer:authReviewer()});}else{await post('/builds/'+BUILD.build_id+'/rules/'+rid+'/'+how,{reason:'UI review'});}vApproval();}
async function patchDecide(how){const map={approve:'APPROVE_CANDIDATE',reject:'REJECT_PATCH',revision:'REQUEST_REVISION'};let r;
if(isCloud()){r=await post('/builds/'+BUILD.build_id+'/resume',{gate:'patch_approval',decision:map[how],reviewer:authReviewer(),reason:(document.getElementById('revReason')||{}).value||'ok',role:'PROCEDURE_OWNER'});}
else{const m2={approve:'patch/approve',reject:'patch/reject',revision:'patch/request-revision'};r=await post('/builds/'+BUILD.build_id+'/'+m2[how],{reviewer:authReviewer(),reason:(document.getElementById('revReason')||{}).value||'ok',role:'PROCEDURE_OWNER'});}
if(r.code!==200){alert('Blocked: '+JSON.stringify(r.data));}else{if(r.data&&r.data.candidate_version_id){CANDIDATE=r.data.candidate_version_id;}BUILD=await get('/builds/'+BUILD.build_id);vApproval();render();}}
async function activate(){if(isCloud()){const r=await post('/builds/'+BUILD.build_id+'/resume',{gate:'activation',decision:'APPROVE',reviewer:authReviewer(),reason:'Final approval'});document.getElementById('actOut').textContent=JSON.stringify(r.data).slice(0,800);return;}const r=await post('/procedures/'+CANDIDATE+'/activate',{build_id:BUILD.build_id,reviewer:authReviewer(),reason:'Final approval'});document.getElementById('actOut').textContent=JSON.stringify(r.data).slice(0,800);}
/* ---------- Runtime traces (evidence, never auto-accepted) ---------- */
async function vTraces(){loading('Loading runtime traces…');let list=[],cmp=null;try{list=(await get('/traces')).traces||[];if(BUILD){try{cmp=await get('/builds/'+BUILD.build_id+'/trace-compare');}catch(e){}}}catch(e){showErr(e);return;}
const rows=list.map(t=>'<tr><td class="mono">'+esc(t.trace_id)+'</td><td class="mono">'+esc(JSON.stringify(t.case)).slice(0,80)+'</td><td class="mono">'+esc(JSON.stringify(t.outcome)).slice(0,80)+'</td><td>'+esc(t.source||'')+'</td></tr>').join('')||'<tr><td colspan="4" class="mut">no traces ingested yet</td></tr>';
const traceEmpty=list.length?'':'<div class="empty" role="status"><i class="ph ph-radioactive e-ico" aria-hidden="true"></i><b>No traces ingested yet.</b> Paste a case in the ingest form and add your first trace.<br/><br/><button class="btn sm" onclick="document.getElementById(\'traceCase\').focus()">Ingest your first trace</button></div>';
const cres=(cmp&&cmp.results)||[];
const crows=cres.map(r=>r.status==='SKIPPED'?'<tr><td class="mono">'+esc(r.trace_id)+'</td><td><span class="tag warn">SKIPPED</span></td><td colspan="3" class="mut">'+esc(r.detail||'')+'</td></tr>':'<tr><td class="mono">'+esc(r.trace_id)+'</td><td><span class="tag '+(r.vs_stale.status==='AGREE'?'pass':'fail')+'">'+esc(r.vs_stale.status)+'</span> '+esc((r.vs_stale.mismatches||[]).join(',')||'—')+'</td><td><span class="tag '+(r.vs_patched.status==='AGREE'?'pass':'fail')+'">'+esc(r.vs_patched.status)+'</span> '+esc((r.vs_patched.mismatches||[]).join(',')||'—')+'</td><td class="mut">'+esc(r.note||'')+'</td><td>'+(r.vs_stale.status==='DISAGREE'&&BUILD?'<button class="btn ghost sm" onclick="nominateTrace(\''+esc(r.trace_id)+'\')" title="Push this case through the verified build pipeline — never witness-by-assertion">Nominate witness</button>':'<span class="mut">—</span>')+'</td></tr>').join('')||'<tr><td colspan="5" class="mut">compile a build to compare traces against it</td></tr>';
setView('<div class="card"><p class="kicker">Runtime traces — real-world evidence (read-only)</p><div class="card-head"><h3>Traces</h3></div>'
+'<p class="mut">Ingest executed decisions; the engine replays each case deterministically and reports agreement. Traces are evidence only — they never become witnesses without the verified build pipeline.</p>'
+traceEmpty
+'<div class="cols2"><div class="card flat"><p class="kicker">Comparison summary</p><div class="mono">'+(cmp?('checked: '+esc(cmp.checked)+' · agree: '+esc(cmp.agree)+' · disagree: '+esc(cmp.disagree)):'no build selected')+'</div><div class="mut">'+esc((cmp&&cmp.honesty_note)||'')+'</div></div>'
+'<div class="card flat"><p class="kicker">Ingest a trace</p><label class="field" for="traceCase">Case JSON</label><textarea id="traceCase" rows="3" placeholder=\'{"cgpa":7.8,"amount":40000,"year":3}\'></textarea><br/>'
+'<label class="field"><input type="checkbox" id="trElig" checked/> eligible</label> <label class="field"><input type="checkbox" id="trOntime" checked/> on_time</label> <label class="field">source <input id="trSource" value="manual" style="width:110px"/></label> '
+'<button class="btn sm" onclick="ingestTrace()">Ingest trace</button><div id="traceOut" class="mono" role="status"></div></div></div>'
+'<div class="card flat"><p class="kicker">Bulk ingest (CSV)</p><p class="mut">Header row required; case columns = every non-reserved column (reserved: eligible, on_time, prohibited, required, steps_done, source, workflow_id, occurred_at). All-or-nothing — one bad row fails the batch; duplicate rows are skipped.</p>'
+'<textarea id="traceCsv" rows="4" class="mono" placeholder="cgpa,amount,eligible,on_time\n7.9,40000,true,true\n8.2,51000,true,true"></textarea><br/>'
+'<button class="btn sm" onclick="ingestCsv()">Ingest CSV</button> <span id="csvOut" class="mono" role="status"></span></div>'
+'<div class="card flat"><p class="kicker">Comparison vs this build</p><table><thead><tr><th>trace</th><th>vs stale procedure</th><th>vs patched preview</th><th>note</th><th>action</th></tr></thead><tbody>'+crows+'</tbody></table></div>'
+'<div class="card flat"><p class="kicker">Stored traces ('+list.length+')</p><table><thead><tr><th>id</th><th>case</th><th>outcome</th><th>source</th></tr></thead><tbody>'+rows+'</tbody></table></div></div>');}
async function ingestTrace(){let c;try{c=JSON.parse(document.getElementById('traceCase').value||'{}');}catch(e){alert('case must be valid JSON');return;}
const body={case:c,outcome:{eligible:document.getElementById('trElig').checked,on_time:document.getElementById('trOntime').checked},source:document.getElementById('trSource').value||'manual',workflow_id:(BUILD&&BUILD.procedure||{}).workflow_id||null};
const r=await post('/traces',body);const el=document.getElementById('traceOut');if(el)el.textContent=r.code===200?('ingested '+(r.data&&r.data.trace_id||'')):('error: '+JSON.stringify(r.data));vTraces();}
async function ingestCsv(){const csv=document.getElementById('traceCsv').value;if(!csv.trim()){alert('paste CSV first');return;}const r=await post('/traces/csv',{csv:csv,workflow_id:(BUILD&&BUILD.procedure||{}).workflow_id||null});const el=document.getElementById('csvOut');if(r.code!==200){if(el)el.textContent='error: '+((r.data&&r.data.error)||JSON.stringify(r.data));}else{if(el)el.textContent='ingested '+r.data.ingested+' · duplicates '+r.data.duplicates;}vTraces();}
async function nominateTrace(tid){if(!BUILD)return;loading('Verifying nominated witness through the build pipeline…');const r=await post('/builds/'+BUILD.build_id+'/nominate-witness',{trace_id:tid,reviewer:authReviewer()});if(r.code!==200){alert('Refused: '+((r.data&&r.data.error)||JSON.stringify(r.data)));return;}const d=r.data||{};if(d.verified){BUILD=await get('/builds/'+BUILD.build_id);}vTraces();if(d.verified){setTimeout(()=>alert('Witness '+d.witness.witness_id+' verified via the build pipeline and added to this build.'),50);}else{setTimeout(()=>alert(d.reason||'pipeline found no new witness for this case'),50);}}
/* ---------- Benchmarks ---------- */
async function vBench(){loading('Loading benchmark…');try{BENCH=await get('/benchmark-runs/latest');}catch(e){setView('<div class="card"><div class="empty" role="status"><i class="ph ph-chart-bar e-ico" aria-hidden="true"></i><b>No benchmark runs yet.</b> Generate one with <span class="mono">make benchmark</span> in a terminal.<br/><br/><button class="btn ghost sm" onclick="try{navigator.clipboard.writeText(\'make benchmark\');this.textContent=\'Copied — paste it in a terminal\';}catch(e){}">Copy command</button></div></div>');return;}
const m={};(BENCH.cases||[]).forEach(c=>{const f=c.case_id.split('-')[0];m[f]=m[f]||{};m[f][c.status]=(m[f][c.status]||0)+1;});
const st={};(BENCH.cases||[]).forEach(c=>{st[c.status]=(st[c.status]||0)+1;});
const cards=[['scenarios',(BENCH.cases||[]).length],['auto repaired',st.AUTO_REPAIRED||0],['correct no-op',st.CORRECTLY_NO_OP||0],['correctly escalated',st.CORRECTLY_ESCALATED||0],['unsupported (boundary shown)',st.UNSUPPORTED||0]];
setView('<div class="card"><p class="kicker">ProcessPatchBench</p><div class="card-head"><h3>More than one scripted demo?</h3></div><div class="cols5">'+cards.map(a=>'<div class="card flat stat"><div class="num">'+esc(a[1])+'</div><div class="lbl">'+esc(a[0])+'</div></div>').join('')+'</div>'
+'<table><thead><tr><th>family</th><th>results</th></tr></thead><tbody>'+Object.entries(m).map(([k,v])=>'<tr><td>'+esc(k)+'</td><td class="mono">'+esc(JSON.stringify(v))+'</td></tr>').join('')+'</tbody></table>'
+'<table><thead><tr><th>case</th><th>split</th><th>status</th></tr></thead><tbody>'+(BENCH.cases||[]).map(c=>'<tr><td>'+esc(c.case_id)+'</td><td>'+esc(c.split||'')+'</td><td>'+esc(c.status)+'</td></tr>').join('')+'</tbody></table>'
+'<p><small>Downstream repair uses gold Rule IR; the eval split is authored/frozen, not an external real-world benchmark.</small></p></div>');}
/* ---------- Builds (workspaces + history) ---------- */
async function vHist(){let ws=[],vers=[];try{[ws,vers]=await Promise.all([get('/workspaces').then(d=>d.workspaces||[]),get('/procedures').then(d=>d.versions||[])]);}catch(e){}
const versBlock=vers.length?'<table><thead><tr><th>version</th><th>workflow</th><th>status</th><th></th></tr></thead><tbody>'+vers.map(v=>'<tr><td class="mono">'+esc(v.procedure_version_id)+'</td><td class="mono">'+esc(v.workflow_id||'—')+'</td><td>'+esc(v.status||'')+'</td><td><button class="btn ghost sm" onclick="buildAgainst(\''+esc(v.procedure_version_id)+'\')">Compile amendment</button></td></tr>').join('')+'</tbody></table>':'<div class="empty" role="status"><i class="ph ph-flow-arrow e-ico" aria-hidden="true"></i><b>No procedures registered.</b> Paste a procedure graph below and register it.<br/><br/><button class="btn ghost sm" onclick="document.getElementById(\'procJson\').focus()">Register a procedure</button></div>';
const wsBlock=ws.length?'<table><thead><tr><th>id</th><th>name</th></tr></thead><tbody>'+ws.map(w=>'<tr><td class="mono">'+esc(w.workspace_id)+'</td><td>'+esc(w.name)+'</td></tr>').join('')+'</tbody></table>':'<div class="empty" role="status"><i class="ph ph-stack e-ico" aria-hidden="true"></i><b>No workspaces yet.</b> Name one below and create it.<br/><br/><button class="btn ghost sm" onclick="document.getElementById(\'wsName\').focus()">Create a workspace</button></div>';
const histBlock=HISTORY.length?'<table><thead><tr><th>build</th><th>status</th><th></th></tr></thead><tbody>'+HISTORY.map(b=>'<tr><td class="mono">'+esc(b.build_id||b)+'</td><td>'+esc(b.status||'')+'</td><td><button class="btn ghost sm" onclick="openBuild(\''+esc(b.build_id||b)+'\')">Open</button></td></tr>').join('')+'</tbody></table>':'<div class="empty" role="status"><i class="ph ph-stack e-ico" aria-hidden="true"></i><b>No builds yet.</b> Compile your first amendment to see it here.<br/><br/><button class="btn sm" onclick="runBuild()">Compile Amendment</button></div>';
setView('<div class="card"><p class="kicker">Workspaces — any registered procedure can be compiled</p><div class="card-head"><h3>Procedures + workspaces</h3></div>'
+'<p class="mut">Demo domains ship built-in; register your own procedure graph (JSON) and compile amendments against it. INVALID_WORKFLOW registrations are rejected fail-closed.</p>'
+'<div class="cols2"><div class="card flat"><p class="kicker">Registered procedure versions ('+vers.length+')</p>'
+versBlock
+'<label class="field" for="procJson">Procedure JSON</label><textarea id="procJson" rows="5" placeholder=\'{"workflow_id":"WF-MY","procedure_version_id":"WF-MY-V1","nodes":[],"edges":[]}\'></textarea><br/><button class="btn sm" onclick="registerProc()">Register procedure</button><div id="procOut" class="mono" role="status"></div></div>'
+'<div class="card flat"><p class="kicker">Workspaces ('+ws.length+')</p>'+wsBlock
+'<label class="field">New workspace <input id="wsName" value="" placeholder="Fellowships 2027"/></label> <button class="btn ghost sm" onclick="createWs()">Create</button></div></div>'
+'<div class="card flat"><p class="kicker">Build history</p>'+(EXECArn?'<p class="mut">active execution: '+esc(EXECArn)+'</p>':'')+histBlock+'</div></div>');}
async function registerProc(){let wf;try{wf=JSON.parse(document.getElementById('procJson').value||'{}');}catch(e){alert('procedure must be valid JSON');return;}
const r=await post('/procedures',{procedure:wf});const el=document.getElementById('procOut');
if(el)el.textContent=r.code===200?('registered '+(r.data&&r.data.procedure_version_id||'')):('rejected: '+JSON.stringify(r.data).slice(0,300));vHist();}
async function createWs(){const n=(document.getElementById('wsName')||{}).value||'';const r=await post('/workspaces',{name:n});if(r.code!==200){alert('error: '+JSON.stringify(r.data));}vHist();}
async function buildAgainst(pid){loading('Compiling amendment against '+pid+'…');const r=await post('/builds',{procedure_version_id:pid});
if(r.code!==200){showErr(new Error(JSON.stringify(r.data).slice(0,200)));return;}
BUILD=r.data;drilled=null;CANDIDATE=null;EXECArn=null;active='Overview';renderTabs();render();loadHistory();}
async function openBuild(id){try{BUILD=await get('/builds/'+id);}catch(e){showErr(e);return;}CANDIDATE=null;active='Overview';renderTabs();render();}
/* ---------- Judge mode ---------- */
const JSTEPS=[['See the stale portal','Overview','Enter CGPA 7.80 and check: the portal rejects a student the policy calls eligible.'],['Compile the amendment','Overview','Click Compile Amendment (or Run Cloud Execution for the Step Functions path).'],['Meet the person who proves the bug','Witnesses','Each card is a verified failing case with expected vs actual paths.'],['Inspect the localized repair','Procedure','Click any node: why it exists, witnesses, patch ops. Red = stale, green = added.'],['Run regression tests','Tests','12+ checks: witnesses, boundaries, preservation, integrity.'],['Approve and replay','Approval','Review exact hashes, approve the candidate, activate, replay the portal.']];
function toggleJudge(){JUDGE=!JUDGE;const hc=document.getElementById('hdrControls');if(hc)hc.style.display=JUDGE?'none':'';const jb=document.getElementById('judgebar');const main=document.getElementById('view');if(JUDGE){JSTEP=0;if(main)main.classList.add('with-judge');go('Overview');judgeShow();jb.style.display='flex';}else{if(main)main.classList.remove('with-judge');jb.style.display='none';}}
function judgeShow(){const s=JSTEPS[JSTEP];const t=s[0],tab=s[1],txt=s[2];document.getElementById('judgebar').innerHTML='<span class="judge-track" style="width:'+Math.round(100*(JSTEP+1)/6)+'%"></span><b class="jstep">JUDGE MODE '+(JSTEP+1)+'/6 · '+esc(t)+'</b><span class="jdesc">'+esc(txt)+'</span><span class="sp"></span><button class="btn ghost sm" onclick="JSTEP=Math.max(0,JSTEP-1);judgeShow()">Back</button><button class="btn sm" onclick="JSTEP=Math.min(5,JSTEP+1);go(JSTEPS[JSTEP][1]);judgeShow()">Next</button><button class="btn ghost sm" onclick="toggleJudge()">Exit</button>';if(active!==tab)go(tab);}
document.addEventListener('keydown',e=>{if(e.key==='Escape'){const dr=document.getElementById('drawerRoot');if(dr&&dr.firstChild)closedrawer();}});
/* ---------- Command palette (Ctrl+K / Cmd+K) — tabs + real actions ---------- */
function paletteItems(){const items=TABS.map(t=>({label:t,hint:'go to tab',icon:NAV_ICONS[t]||'square',run:()=>go(t)}));
items.push(
 {label:'Compile Amendment',hint:'run the local deterministic pipeline',icon:'lightning',run:()=>runBuild()},
 {label:'Run Cloud Execution',hint:'Step Functions path',icon:'cloud-arrow-up',run:()=>cloudRun()},
 {label:'Toggle theme',hint:'lab → paper → graphite',icon:'palette',run:()=>toggleTheme()},
 {label:'Judge Mode',hint:'scripted 6-step walkthrough',icon:'chalkboard-teacher',run:()=>toggleJudge()},
 {label:'Download governance bundle',hint:'sha256-sealed evidence pack (approval required)',icon:'seal-check',run:()=>downloadBundle()},
 {label:'Compile pasted policy',hint:'extract + compile the text in Policy input',icon:'brackets-curly',run:()=>{go('Overview');setTimeout(submitPolicy,60);}});
return items;}
let PAL={open:false,idx:0,items:[]};
function openPalette(){if(PAL.open)return;PAL={open:true,idx:0,items:paletteItems()};
const root=document.getElementById('drawerRoot');const ov=document.createElement('div');ov.id='palOverlay';
ov.innerHTML='<div class="pal" role="dialog" aria-modal="true" aria-label="Command palette"><input id="palInput" type="text" placeholder="Type a command… (tabs, compile, traces, theme)" autocomplete="off"/><div id="palList" role="listbox" aria-label="Commands"></div><div class="pal-foot"><small>↑↓ navigate · Enter run · Esc close</small></div></div>';
root.appendChild(ov);ov.addEventListener('mousedown',e=>{if(e.target===ov)closePalette();});
const inp=document.getElementById('palInput');inp.addEventListener('input',()=>palRender());
inp.addEventListener('keydown',e=>{
 if(e.key==='ArrowDown'){e.preventDefault();PAL.idx=Math.min(PAL.idx+1,palFiltered().length-1);palRender(true);}
 else if(e.key==='ArrowUp'){e.preventDefault();PAL.idx=Math.max(0,PAL.idx-1);palRender(true);}
 else if(e.key==='Enter'){e.preventDefault();const f=palFiltered();const it=f[PAL.idx];if(it){closePalette();it.run();}}
 else if(e.key==='Escape'){e.preventDefault();closePalette();}});
palRender();inp.focus();}
function palFiltered(){const q=(document.getElementById('palInput')||{value:''}).value.trim().toLowerCase();
let items=PAL.items;if(q)items=items.filter(it=>(it.label+' '+it.hint).toLowerCase().includes(q));
return items;}
function palRender(keepIdx){const list=document.getElementById('palList');if(!list)return;const f=palFiltered();
if(!keepIdx)PAL.idx=Math.min(PAL.idx,Math.max(0,f.length-1));
list.innerHTML=f.map((it,i)=>'<div class="pal-item'+(i===PAL.idx?' sel':'')+'" role="option" aria-selected="'+(i===PAL.idx)+'" data-i="'+i+'"><i class="ph ph-'+esc(it.icon)+'" aria-hidden="true"></i><b>'+esc(it.label)+'</b><small>'+esc(it.hint)+'</small></div>').join('')||'<div class="pal-item mut">no matching command</div>';
[...list.querySelectorAll('.pal-item[data-i]')].forEach(n=>{n.addEventListener('click',()=>{const it=f[+n.dataset.i];closePalette();it.run();});n.addEventListener('mousemove',()=>{PAL.idx=+n.dataset.i;[...list.children].forEach((c,j)=>c.classList.toggle('sel',j===PAL.idx));});});
const sel=list.querySelector('.pal-item.sel');if(sel)sel.scrollIntoView({block:'nearest'});}
function closePalette(){PAL.open=false;const ov=document.getElementById('palOverlay');if(ov)ov.remove();}
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&(e.key==='k'||e.key==='K')){e.preventDefault();if(PAL.open)closePalette();else openPalette();}});
try{const ab=document.getElementById('apiBase');if(ab&&window.PROCESSPATCH_API)ab.value=window.PROCESSPATCH_API;}catch(e){}
renderTabs();render();authLoad();authFetchCfg().then(()=>authMaybeExchange()).then(()=>renderTabs());loadHistory();
