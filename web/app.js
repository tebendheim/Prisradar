import {createClient} from 'https://esm.sh/@supabase/supabase-js@2.89.0';
import {SUPABASE_URL,SUPABASE_KEY} from './config.js';
const $=id=>document.getElementById(id), client=createClient(SUPABASE_URL,SUPABASE_KEY);
const status=s=>($('app').hidden?$('authStatus'):$('status')).textContent=s;
let isAdmin=false;
function showView(view){if(!['search','watches','coupons','admin'].includes(view)||view==='admin'&&!isAdmin)view='search';for(const v of ['search','watches','coupons','admin'])$(v+'View').hidden=v!==view;for(const b of document.querySelectorAll('[data-view]')){if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')}if(view==='admin'){refreshAdmin();loadStores()}if(view==='coupons')$('coupons').click()}
for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>showView(b.dataset.view);
document.querySelector('.brand').onclick=e=>{e.preventDefault();if(!$('app').hidden)showView('search')};
function fail(e){status(e?.message||String(e))}
function node(tag,text,parent){const n=document.createElement(tag);n.textContent=text;parent.append(n);return n}
function link(parent,url,label){try{const u=new URL(url);if(u.protocol==='https:'){const a=node('a',label,parent);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer'}}catch{}}
async function session(s){clearTimeout(pollTimer);clearSuggestions();searchVersion++;selectedModel=null;isAdmin=false;adminPanel.hidden=true;$('adminTab').hidden=true;$('logout').hidden=true;$('app').hidden=true;$('login').hidden=false;$('status').textContent='';for(const id of ['results','discounts','watches']) $(id).replaceChildren();if(!s)return;const {data,error}=await client.from('members').select('role').eq('user_id',s.user.id).maybeSingle();if(error||!data){status('Kontoen er ikke invitert.');await client.auth.signOut();return}$('login').hidden=true;$('app').hidden=false;$('authStatus').textContent='';$('logout').hidden=false;isAdmin=data.role==='admin';adminPanel.hidden=!isAdmin;$('adminTab').hidden=!isAdmin;showView('search');await watches()}
$('loginForm').onsubmit=async e=>{e.preventDefault();const {data,error}=await client.auth.signInWithPassword({email:$('email').value,password:$('password').value});$('password').value='';if(error)fail(error);else await session(data.session)};
$('logout').onclick=async()=>{clearSuggestions();searchVersion++;await client.auth.signOut();await session(null);status('Logget ut')};
// Suggestions are from indexed offers, never invented product prices.
const qInput=$('q'), suggestionBox=document.createElement('div');
suggestionBox.id='suggestions';suggestionBox.setAttribute('aria-label','Produktforslag');
qInput.parentElement.append(suggestionBox);
let suggestTimer, suggestVersion=0, searchVersion=0, selectedModel=null;
async function models(q){const {data,error}=await client.rpc('browse_models_v1',{q});if(error)throw error;return [...new Set((data||[]).map(x=>x.name))]}
function chooseModel(name){selectedModel=name;qInput.value=name;clearSuggestions();$('searchForm').requestSubmit()}
async function browseCategory(q,names){clearTimeout(pollTimer);const version=++searchVersion;const root=$('results');root.replaceChildren();status('Registrerer prisoppdatering for produktgruppen …');try{const selected=names.slice(0,12);let queued=0;for(const name of selected){if(version!==searchVersion)return;const r=await client.rpc('touch_search_v1',{q:name});if(!r.error&&r.data.due)queued++}if(queued&&isAdmin&&version===searchVersion&&!$('app').hidden){try{await crawlerRequest('POST')}catch{}}const deadline=Date.now()+9*60*1000;async function refresh(){if(version!==searchVersion||$('app').hidden)return;const {data,error}=await client.rpc('category_offers_v1',{q});if(version!==searchVersion)return;if(error){fail(error);return}renderCategory(data,names,q);status(data.length+' lagrede tilbud. '+(queued?'Opptil '+selected.length+' modeller registrert for oppdatering; flere kan fortsatt vente i kø.':'Ingen ny oppdatering nødvendig for valgte modeller.'));if(queued&&Date.now()<deadline)pollTimer=setTimeout(refresh,10000)}await refresh()}catch(e){if(version===searchVersion)fail(e)}}
function modelLabel(n){if(/^(apple )?airpods pro 3(?:[ .]|$)/i.test(n)&&!/deksel|reservedel|replacement|case only|etui alene|tilbehør/i.test(n))return 'Apple AirPods Pro 3';if(/^(apple )?airpods pro 2(?:[ .]|$)/i.test(n)&&!/deksel|reservedel|replacement|case only|etui alene/i.test(n))return 'Apple AirPods Pro 2';return n}
function renderCategory(data,names,q){const root=$('results');root.replaceChildren();const groups=new Map(names.map(n=>[n,[]]));for(const r of data){const label=modelLabel(r.name);if(!groups.has(label))groups.set(label,[]);groups.get(label).push(r)}$('resultCount').textContent=groups.size+' modeller';for(const [name,rows] of groups){const card=node('article','',root);node('strong',name,card);const available=rows.filter(r=>!['OutOfStock','SoldOut','Discontinued'].includes(r.availability));const known=available.filter(r=>r.shipping!=null&&r.total_price!=null).sort((a,b)=>a.total_price-b.total_price);const unknown=available.filter(r=>r.shipping==null).sort((a,b)=>a.price-b.price);if(known.length)node('p','Fra '+known[0].total_price+' kr inkl. frakt · '+known[0].host,card);if(unknown.length)node('small','Fra '+unknown[0].price+' kr + ukjent frakt · '+unknown[0].host,card);if(!available.length)node('p','Ingen tilgjengelige dokumenterte tilbud ennå',card);if(available.length){const latest=Math.max(...available.map(r=>Date.parse(r.checked)).filter(Number.isFinite));if(Number.isFinite(latest))node('small','Nyeste kontroll: '+new Date(latest).toLocaleString('nb-NO'),card)}const b=node('button','Se butikktilbud',card);b.type='button';b.onclick=()=>chooseModel(name)}}
function renderModels(names,q){const root=$('results');root.replaceChildren();$('resultCount').textContent=names.length+' modeller';node('h3','Velg produktmodell',root);const all=node('button','Sammenlign priser på alle modeller',root);all.type='button';all.onclick=()=>browseCategory(q,names);for(const name of names){const card=node('article','',root);const b=node('button',name,card);b.type='button';b.className='model-choice';b.onclick=()=>chooseModel(name)}const b=node('button','Søk etter priser på «'+q+'» likevel',root);b.type='button';b.className='quiet';b.onclick=()=>chooseModel(q)}
function clearSuggestions(){clearTimeout(suggestTimer);suggestVersion++;suggestionBox.replaceChildren()}
qInput.addEventListener('input',()=>{
  selectedModel=null;clearSuggestions(); const q=qInput.value.trim(), version=suggestVersion;
  if(q.length<2)return;
  suggestTimer=setTimeout(async()=>{
    const pattern=q.replace(/[%_\\]/g,'').split(/\s+/).join('%');
    if(!pattern)return;
    const {data,error}=await client.rpc('suggest_products_v1',{q});
    if(version!==suggestVersion||error||$('app').hidden)return;
    for(const name of [...new Set(data.map(x=>x.name))].slice(0,8)){
      const b=node('button',name,suggestionBox);b.type='button';b.style.display='block';b.style.width='100%';b.style.textAlign='left';
      b.onclick=()=>chooseModel(name);
    }
  },300);
});
qInput.addEventListener('keydown',e=>{if(e.key==='Escape')clearSuggestions()});
let pollTimer;
async function showCoverage(root,q,version){
 const res=await client.rpc('store_search_status_v1',{q});
 if(version!==searchVersion||!root.isConnected)return;
 if(res.error){node('small','Butikkstatus utilgjengelig: '+res.error.message,root);return}
 const stores=res.data?.stores||[];const checked=stores.filter(s=>s.checked).length;
 node('p',checked+' av '+stores.length+' registrerte butikker forsøkt · '+stores.filter(s=>s.status==='found').length+' med treff',root);
 const details=node('details','',root);node('summary','Vis butikkstatus',details);
 for(const s of stores)node('p',s.host+' · '+({pending:'Venter',found:'Treff',no_offer:'Ingen dokumentert pris',incomplete:'Ufullstendig'}[s.status]||s.status)+(s.detail?' · '+s.detail:''),details);
}
function renderOffers(data,q){
 const root=$('results');root.replaceChildren();$('resultCount').textContent=data.length+' treff';const coverage=node('section','',root);showCoverage(coverage,q,searchVersion);if(isAdmin){const b=node('button','Oppdater priser nå',coverage);b.type='button';b.onclick=async()=>{b.disabled=true;try{const r=await client.rpc('refresh_search_v1',{q});if(r.error)throw r.error;chooseModel(q)}catch(e){fail(e);b.disabled=false}}}
 for(const r of data){
  const card=node('article','',root);card.className='offer';const info=node('div','',card);node('strong',r.name,info);node('small',r.host,info);node('small',(r.availability||'Ukjent lagerstatus')+' · kontrollert '+new Date(r.checked).toLocaleString('nb-NO'),info);link(info,r.url,'Åpne butikk');const price=node('div','',card);const amount=node('div',new Intl.NumberFormat('nb-NO',{maximumFractionDigits:2}).format(r.total_price??r.price)+' kr',price);amount.className='offer-price';node('small',r.shipping==null?'Frakt ukjent':'Inkl. frakt',price);
 }
 if(!data.length){node('p','Ingen dokumenterte treff ennå. Dette betyr ikke at varen ikke selges.',root);const b=node('button','Lagre som prisønske',root);b.type='button';b.onclick=()=>{showView('watches');$('watchQuery').value=q;$('target').focus()}}
}
async function pollResults(q,version,deadline,previousAttempt,notice=''){
 if(version!==searchVersion||$('app').hidden)return;
 try{
  const [offers,progress]=await Promise.all([client.rpc('search_offers_v1',{q,max_results:100}),client.rpc('search_progress_v1',{q})]);
  if(version!==searchVersion||$('app').hidden)return;
  if(offers.error)throw offers.error;
  renderOffers(offers.data,q);
  const p=progress.data;const finished=!progress.error&&p?.last_attempt&&p.last_attempt!==previousAttempt;
  status(offers.data.length+' dokumenterte treff. '+(finished?'Prisinnhenting avsluttet.':notice||'Venter på prisoppdatering …'));
  if(!finished&&Date.now()<deadline)pollTimer=setTimeout(()=>pollResults(q,version,deadline,previousAttempt,notice),10000);
  else if(!finished)status(offers.data.length+' dokumenterte treff. Automatisk visning avsluttet; søket beholdes i kø.');
 }catch(e){if(version===searchVersion)fail(e)}
}
$('searchForm').onsubmit=async e=>{
 e.preventDefault();clearSuggestions();clearTimeout(pollTimer);const version=++searchVersion;
 try{
  const q=qInput.value.trim();if(!q)return;
  status('Finner produktmodeller …');
  if(selectedModel!==q){const names=await models(q);if(version!==searchVersion||$('app').hidden)return;if(names.length===1&&names[0].toLowerCase()===q.toLowerCase()){selectedModel=q}else if(names.length){renderModels(names,q);status('Velg modellen du vil sammenligne priser på.');return}}
  selectedModel=null;status('Henter priser …');
  const tracked=await client.rpc('touch_search_v1',{q});if(tracked.error)throw tracked.error;
  const [offers,progress]=await Promise.all([client.rpc('search_offers_v1',{q,max_results:100}),client.rpc('search_progress_v1',{q})]);
  if(version!==searchVersion||$('app').hidden)return;
  if(offers.error)throw offers.error;
  renderOffers(offers.data,q);
  status(offers.data.length+' dokumenterte treff. '+(tracked.data.due?'Prisoppdatering i kø.':'Lagrede priser.'));
  if(tracked.data.due&&version===searchVersion&&!$('app').hidden){
   const previous=progress.data?.last_attempt;
   let notice='Venter på crawleren …';
   if(isAdmin){try{await crawlerRequest('POST');notice='Prisinnhenting startet …'}catch(e){notice=e.message.includes('allerede')?'En annen prisinnhenting pågår. Ditt søk er i kø.':'Søket beholdes i kø: '+e.message}}
   if(version===searchVersion)pollResults(q,version,Date.now()+9*60*1000,previous,notice);
  }
 }catch(e){if(version===searchVersion)fail(e)}
};
$('coupons').onclick=async()=>{const {data,error}=await client.from('coupons').select('*').order('checked',{ascending:false}).limit(100);if(error)return fail(error);const root=$('discounts');root.replaceChildren();for(const r of data){const c=node('article',r.host+' · '+r.code+' · '+r.status,root);node('small',r.context||'',c);link(c,r.source,'Kilde')}};
async function watches(){const {data,error}=await client.from('watches').select('*');if(error)return fail(error);const root=$('watches');root.replaceChildren();for(const r of data){const c=node('article',r.query+' · '+r.target+' kr',root);const b=node('button','Slett',c);b.onclick=async()=>{const res=await client.from('watches').delete().eq('id',r.id);if(res.error)fail(res.error);else watches()}}}
$('watchForm').onsubmit=async e=>{e.preventDefault();const {error}=await client.from('watches').insert({query:$('watchQuery').value,target:Number($('target').value)});if(error)fail(error);else{status('Prisønske lagret (varsling er ikke aktivert ennå).');watches()}};
const adminPanel=document.createElement('div');adminPanel.id='adminPanel';adminPanel.hidden=true;$('adminView').append(adminPanel);
const crawlerPanel=node('section','',adminPanel);node('h2','Crawler og produktindeks',crawlerPanel);
const adminInfo=node('p','',crawlerPanel), runInfo=node('p','',crawlerPanel);
const startButton=node('button','Start indeksering',crawlerPanel);
const refreshButton=node('button','Oppdater status',crawlerPanel);
startButton.type=refreshButton.type='button';runInfo.setAttribute('role','status');runInfo.setAttribute('aria-live','polite');
const schemaPanel=node('section','',adminPanel);node('h3','Database og migreringer',schemaPanel);const schemaInfo=node('p','Ikke kontrollert ennå',schemaPanel);link(schemaPanel,'https://github.com/tebendheim/Prisradar/blob/main/supabase/migrations/2026112704.sql','Åpne nødvendig SQL-migrering');
const quotaPanel=node('section','',adminPanel);node('h3','Kjørekvote',quotaPanel);const quotaInfo=node('p','Henter kvote …',quotaPanel);const extraButton=node('button','Start ekstra kjøring',quotaPanel);extraButton.type='button';extraButton.disabled=true;node('small','Interne grenser, ikke GitHubs faktiske faktureringssaldo. Ekstra kjøringer bruker samme 30-dagerskvote.',quotaPanel);link(quotaPanel,'https://github.com/settings/billing','Se faktisk GitHub-forbruk');const logPanel=node('section','',adminPanel);node('h3','Kjørelogg',logPanel);link(logPanel,'https://github.com/tebendheim/Prisradar/actions','Alle GitHub-kjøringer');const runList=node('div','',logPanel);runList.id='runList';const reportList=node('div','',logPanel);
const storesPanel=node('section','',adminPanel);node('h3','Nettbutikker',storesPanel);
const storeHost=node('input','',storesPanel);storeHost.placeholder='www.butikk.no';storeHost.setAttribute('aria-label','Butikkdomene');storeHost.autocapitalize='none';
const storePath=node('input','',storesPanel);storePath.placeholder='Oppdages automatisk (valgfri overstyring)';storePath.setAttribute('aria-label','Søkesti');
const feedPath=node('input','',storesPanel);feedPath.placeholder='Oppdages automatisk (valgfri overstyring)';feedPath.setAttribute('aria-label','Tillatt offentlig produktfeed');
const delivery=node('input','',storesPanel);delivery.placeholder='Leveringsinformasjon (valgfritt)';delivery.setAttribute('aria-label','Dokumentasjon på levering til Norge');
const saveStore=node('button','Lagre og aktiver butikk',storesPanel);saveStore.type='button';
const storesList=node('div','',storesPanel);const storeStatus=node('p','',storesPanel);
const candidatePanel=node('details','',storesPanel);node('summary','Oppdagede butikkandidater',candidatePanel);const candidateList=node('div','',candidatePanel);
function editStore(s){storeHost.value=s.host;storePath.value=s.search_path||'';feedPath.value=s.feed_path||'';delivery.value=s.delivery_evidence||'';storeHost.focus()}
async function persistStore(s,active){const r=await client.rpc('configure_store_v1',{h:s.host,p:s.search_path||null,active,feed:s.feed_path||null,evidence:s.delivery_evidence||null});storeStatus.textContent=r.error?r.error.message:'Butikk lagret';if(!r.error)await loadStores();return !r.error}
async function loadStores(){
 const [res,candidates]=await Promise.all([client.from('managed_stores').select('host,search_path,enabled,paused_until,feed_path,delivery_evidence,adapter,vat_status,currency_hint').order('host'),client.from('store_candidates').select('host,source,probe_result,probe_checked').order('host').limit(200)]);
 if(res.error){storeStatus.textContent=res.error.message;return}storesList.replaceChildren();const known=new Set(res.data.map(s=>s.host));
 for(const s of res.data){const row=node('article','',storesList);node('strong',s.host,row);node('small',(s.enabled?'Aktiv':'Deaktivert')+' · '+(s.feed_path?'Produktfeed · ':'')+(s.search_path||'Sitemap')+(s.paused_until&&new Date(s.paused_until)>new Date()?' · midlertidig pause':''),row);node('small','Adapter: '+s.adapter+' · '+(s.vat_status==='norwegian_evidence'?'Signal om norsk MVA':s.vat_status==='vat_mentioned'?'MVA nevnt, land ukjent':'MVA ukjent')+' · '+(s.currency_hint==='NOK'?'NOK observert':'Valuta ukjent'),row);node('small',s.delivery_evidence?'Leveringsgrunnlag: '+s.delivery_evidence:'Levering ikke dokumentert i registeret',row);const edit=node('button','Rediger',row);edit.type='button';edit.onclick=()=>editStore(s);const toggle=node('button',s.enabled?'Deaktiver':'Aktiver',row);toggle.type='button';toggle.onclick=()=>persistStore(s,!s.enabled)}
 candidateList.replaceChildren();if(candidates.error){node('p',candidates.error.message,candidateList);return}for(const c of candidates.data.filter(x=>!known.has(x.host))){const row=node('article','',candidateList);node('strong',c.host,row);node('small',c.source,row);node('small',c.probe_result||'Venter på automatisk vurdering',row);const b=node('button','Vurder butikk',row);b.type='button';b.onclick=()=>editStore(c)}
}
saveStore.onclick=async()=>{if(await persistStore({host:storeHost.value,search_path:storePath.value,feed_path:feedPath.value,delivery_evidence:delivery.value},true)){storeHost.value='';storePath.value='';feedPath.value='';delivery.value=''}};
async function refreshQuota(){const {data,error}=await client.rpc('crawl_quota_status_v1');if(error){quotaInfo.textContent='Kvoteoversikt utilgjengelig: '+error.message;return null}quotaInfo.textContent='Siste 24 timer: '+data.used_day+' starter. Ordinære igjen: '+data.normal_remaining+'. Ekstra igjen: '+data.extra_remaining+'. Siste 30 dager: '+data.used_30d+' av '+data.manual_cap+' starter. Anslått maksimalt manuelt forbruk: '+data.estimated_max_minutes_30d+' minutter. Tidligste mulige ekstra start: '+new Date(data.next_start).toLocaleString('nb-NO');return data}
let adminBusy=false;
async function crawlerRequest(method,extra=false){
 const {data}=await client.auth.getSession();if(!data.session)throw Error('Logg inn på nytt');
 const r=await fetch('/api/crawler',{method,headers:{Authorization:'Bearer '+data.session.access_token,...(method==='POST'?{'Content-Type':'application/json'}:{})},...(method==='POST'?{body:JSON.stringify({extra})}:{}),cache:'no-store',signal:AbortSignal.timeout(20000)});
 let body;try{body=await r.json()}catch{throw Error('Crawler-API svarte ikke med JSON (HTTP '+r.status+'). Kontroller Cloudflare-publiseringen.')}if(!r.ok)throw Error((body.error||'Backendfeil')+(body.github_status?' (GitHub HTTP '+body.github_status+')':''));return body;
}
async function refreshAdmin(){
 if(adminBusy)return;adminBusy=true;startButton.disabled=true;extraButton.disabled=true;refreshButton.disabled=true;
 runInfo.textContent='Henter crawlerstatus …';
 try{
  const [offers,coupons]=await Promise.all([client.from('offers').select('id',{count:'exact',head:true}),client.from('coupons').select('id',{count:'exact',head:true})]);
  adminInfo.textContent=(offers.error?'Ukjent':offers.count)+' produktoppføringer · '+(coupons.error?'ukjent':coupons.count)+' rabattkoder';
  const reports=await client.from('crawl_reports').select('host,pages,offers,detail,created').order('created',{ascending:false}).limit(20);if(!reports.error){reportList.replaceChildren();for(const report of reports.data)node('p',new Date(report.created).toLocaleString('nb-NO')+' · '+report.host+' · '+report.pages+' sider · '+report.offers+' tilbud · '+report.detail,reportList)}else{reportList.textContent='Butikklogg utilgjengelig: '+reports.error.message}const metrics=await client.rpc('admin_metrics_v1');if(!metrics.error){const m=metrics.data;adminInfo.textContent=m.products+' unike katalogprodukter · '+m.offers+' pristilbud · '+m.pages+' kjente nettadresser · '+m.stores+' aktive butikker · '+m.candidates+' kandidater · '+m.coupons+' rabattkoder'}else{adminInfo.textContent=(offers.error?'Ukjent':offers.count)+' pristilbud (ikke katalogprodukter) · '+(coupons.error?'ukjent':coupons.count)+' rabattkoder'}const data=await crawlerRequest('GET');schemaInfo.textContent=data.health?.ready?'Database klar · versjon '+data.health.version:'Database må oppdateres · versjon '+(data.health?.version||0)+' · '+(data.health?.missing||[]).join(', ');runInfo.textContent=data.active?'Crawleren er i gang eller i kø.':'Ingen aktiv kjøring.';
  runList.replaceChildren();
  for(const r of data.runs.slice(0,5)){
   const row=node('p',new Date(r.created_at).toLocaleString('nb-NO')+' · '+(r.conclusion||r.status),runList);
   link(row,'https://github.com/tebendheim/Prisradar/actions/runs/'+r.id,'  Logg');
  }

  const quota=await refreshQuota();
  startButton.disabled=!data.health?.ready||data.active||!!(quota&&quota.normal_remaining===0);
  extraButton.disabled=!data.health?.ready||data.active||!quota||quota.extra_remaining===0;
 }catch(e){runInfo.textContent='Statusfeil: '+e.message;startButton.disabled=true;extraButton.disabled=true;schemaInfo.textContent='Kontroll utilgjengelig: '+e.message}
 finally{adminBusy=false;refreshButton.disabled=false}
}
async function startCrawler(extra=false){if(adminBusy)return;adminBusy=true;startButton.disabled=true;extraButton.disabled=true;refreshButton.disabled=true;
 runInfo.textContent='Sender startforespørsel til GitHub …';startButton.textContent='Starter …';
 let accepted=false;
 try{await crawlerRequest('POST',extra);accepted=true;runInfo.textContent='Startforespørsel akseptert. Henter status …'}
 catch(e){runInfo.textContent='Kunne ikke starte: '+e.message}
 finally{adminBusy=false;refreshButton.disabled=false;startButton.textContent='Start indeksering';startButton.disabled=accepted}
 if(accepted)setTimeout(refreshAdmin,3000);else{await refreshAdmin()}
}
startButton.onclick=()=>startCrawler(false);extraButton.onclick=()=>startCrawler(true);
refreshButton.onclick=()=>{refreshAdmin();loadStores()};
const {data}=await client.auth.getSession();await session(data.session);client.auth.onAuthStateChange((event)=>{if(event==='SIGNED_OUT'){isAdmin=false;searchVersion++;clearTimeout(pollTimer);$('logout').hidden=true;$('adminTab').hidden=true; adminPanel.hidden=true; $('app').hidden=true;$('login').hidden=false;for(const id of ['results','discounts','watches'])$(id).replaceChildren()}});
