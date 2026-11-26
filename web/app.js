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
async function session(s){isAdmin=false;adminPanel.hidden=true;$('adminTab').hidden=true;$('logout').hidden=true;$('app').hidden=true;$('login').hidden=false;$('status').textContent='';for(const id of ['results','discounts','watches']) $(id).replaceChildren();if(!s)return;const {data,error}=await client.from('members').select('role').eq('user_id',s.user.id).maybeSingle();if(error||!data){status('Kontoen er ikke invitert.');await client.auth.signOut();return}$('login').hidden=true;$('app').hidden=false;$('authStatus').textContent='';$('logout').hidden=false;isAdmin=data.role==='admin';adminPanel.hidden=!isAdmin;$('adminTab').hidden=!isAdmin;showView('search');await watches()}
$('loginForm').onsubmit=async e=>{e.preventDefault();const {data,error}=await client.auth.signInWithPassword({email:$('email').value,password:$('password').value});$('password').value='';if(error)fail(error);else await session(data.session)};
$('logout').onclick=async()=>{clearSuggestions();searchVersion++;await client.auth.signOut();await session(null);status('Logget ut')};
// Suggestions are from indexed offers, never invented product prices.
const qInput=$('q'), suggestionBox=document.createElement('div');
suggestionBox.id='suggestions';suggestionBox.setAttribute('aria-label','Produktforslag');
qInput.parentElement.append(suggestionBox);
let suggestTimer, suggestVersion=0, searchVersion=0, selectedModel=null;
async function models(q){const {data,error}=await client.rpc('suggest_products_v1',{q});if(error)throw error;return [...new Set((data||[]).map(x=>x.name))]}
function chooseModel(name){selectedModel=name;qInput.value=name;clearSuggestions();$('searchForm').requestSubmit()}
function renderModels(names,q){const root=$('results');root.replaceChildren();$('resultCount').textContent=names.length+' modeller';node('h3','Velg produktmodell',root);for(const name of names){const card=node('article','',root);const b=node('button',name,card);b.type='button';b.className='model-choice';b.onclick=()=>chooseModel(name)}const b=node('button','Søk etter priser på «'+q+'» likevel',root);b.type='button';b.className='quiet';b.onclick=()=>chooseModel(q)}
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
function renderOffers(data,q){
 const root=$('results');root.replaceChildren();$('resultCount').textContent=data.length+' treff';
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
  if(selectedModel!==q){const names=await models(q);if(version!==searchVersion||$('app').hidden)return;if(names.length){renderModels(names,q);status('Velg modellen du vil sammenligne priser på.');return}}
  selectedModel=null;status('Henter priser …');
  const tracked=await client.rpc('touch_search_v1',{q});if(tracked.error)throw tracked.error;
  const [offers,progress]=await Promise.all([client.rpc('search_offers_v1',{q,max_results:100}),client.rpc('search_progress_v1',{q})]);
  if(version!==searchVersion||$('app').hidden)return;
  if(offers.error)throw offers.error;
  renderOffers(offers.data,q);
  status(offers.data.length+' dokumenterte treff. '+(tracked.data.due?'Prisoppdatering i kø.':'Lagrede priser.'));
  if(tracked.data.due){
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
const quotaPanel=node('section','',adminPanel);node('h3','Kjørekvote',quotaPanel);const quotaInfo=node('p','Henter kvote …',quotaPanel);const extraButton=node('button','Start ekstra kjøring',quotaPanel);extraButton.type='button';extraButton.disabled=true;node('small','Interne grenser, ikke GitHubs faktiske faktureringssaldo. Ekstra kjøringer bruker samme 30-dagerskvote.',quotaPanel);link(quotaPanel,'https://github.com/settings/billing','Se faktisk GitHub-forbruk');const runList=node('div','',crawlerPanel);runList.id='runList';
const storesPanel=node('section','',adminPanel);node('h3','Nettbutikker',storesPanel);const storeHost=node('input','',storesPanel);storeHost.placeholder='www.butikk.no';storeHost.setAttribute('aria-label','Butikkdomene');storeHost.autocapitalize='none';const storePath=node('input','',storesPanel);storePath.placeholder='/search?q={q} (valgfritt)';storePath.setAttribute('aria-label','Søkesti');const saveStore=node('button','Legg til / oppdater butikk',storesPanel);saveStore.type='button';const storesList=node('div','',storesPanel);const storeStatus=node('p','',storesPanel);
async function loadStores(){const {data,error}=await client.from('managed_stores').select('host,search_path,enabled,paused_until').order('host');if(error){storeStatus.textContent=error.message;return}storesList.replaceChildren();for(const s of data){const row=node('article','',storesList);node('strong',s.host,row);node('small',' · '+(s.enabled?'Aktiv':'Deaktivert')+' · '+(s.search_path||'Sitemap')+(s.paused_until&&new Date(s.paused_until)>new Date()?' · midlertidig pause':''),row);const edit=node('button','Rediger',row);edit.type='button';edit.onclick=()=>{storeHost.value=s.host;storePath.value=s.search_path||''};const toggle=node('button',s.enabled?'Deaktiver':'Aktiver',row);toggle.type='button';toggle.onclick=async()=>{const r=await client.rpc('save_store_v1',{h:s.host,p:s.search_path,active:!s.enabled});storeStatus.textContent=r.error?r.error.message:'Butikk oppdatert';if(!r.error)loadStores()}}}
saveStore.onclick=async()=>{const r=await client.rpc('save_store_v1',{h:storeHost.value,p:storePath.value,active:true});storeStatus.textContent=r.error?r.error.message:'Butikk lagret';if(!r.error){storeHost.value='';storePath.value='';loadStores()}};
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
  const reports=await client.from('crawl_reports').select('host,pages,offers,detail,created').order('created',{ascending:false}).limit(8);const data=await crawlerRequest('GET');runInfo.textContent=data.active?'Crawleren er i gang eller i kø.':'Ingen aktiv kjøring.';
  runList.replaceChildren();
  for(const r of data.runs.slice(0,5)){
   const row=node('p',new Date(r.created_at).toLocaleString('nb-NO')+' · '+(r.conclusion||r.status),runList);
   link(row,'https://github.com/tebendheim/Prisradar/actions/runs/'+r.id,'  Logg');
  }
  if(!reports.error){for(const report of reports.data)node('p',report.host+' · '+report.pages+' sider · '+report.offers+' tilbud · '+report.detail,runList)}
  const quota=await refreshQuota();
  startButton.disabled=data.active||!!(quota&&quota.normal_remaining===0);
  extraButton.disabled=data.active||!quota||quota.extra_remaining===0;
 }catch(e){runInfo.textContent='Statusfeil: '+e.message;startButton.disabled=false}
 finally{adminBusy=false;refreshButton.disabled=false}
}
async function startCrawler(extra=false){if(adminBusy)return;adminBusy=true;startButton.disabled=true;extraButton.disabled=true;refreshButton.disabled=true;
 runInfo.textContent='Sender startforespørsel til GitHub …';startButton.textContent='Starter …';
 let accepted=false;
 try{await crawlerRequest('POST',extra);accepted=true;runInfo.textContent='Startforespørsel akseptert. Henter status …'}
 catch(e){runInfo.textContent='Kunne ikke starte: '+e.message}
 finally{adminBusy=false;refreshButton.disabled=false;startButton.textContent='Start indeksering';startButton.disabled=accepted}
 if(accepted)setTimeout(refreshAdmin,3000);else{const quota=await refreshQuota();extraButton.disabled=!quota||quota.extra_remaining===0;startButton.disabled=!!(quota&&quota.normal_remaining===0)}
}
startButton.onclick=()=>startCrawler(false);extraButton.onclick=()=>startCrawler(true);
refreshButton.onclick=()=>{refreshAdmin();loadStores()};
const {data}=await client.auth.getSession();await session(data.session);client.auth.onAuthStateChange((event)=>{if(event==='SIGNED_OUT'){isAdmin=false;searchVersion++;clearTimeout(pollTimer);$('logout').hidden=true;$('adminTab').hidden=true; adminPanel.hidden=true; $('app').hidden=true;$('login').hidden=false;for(const id of ['results','discounts','watches'])$(id).replaceChildren()}});
