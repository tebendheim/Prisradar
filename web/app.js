import {createClient} from 'https://esm.sh/@supabase/supabase-js@2.89.0';
import {SUPABASE_URL,SUPABASE_KEY} from './config.js';
const $=id=>document.getElementById(id), client=createClient(SUPABASE_URL,SUPABASE_KEY);
const status=s=>$('status').textContent=s;
function fail(e){status(e?.message||String(e))}
function node(tag,text,parent){const n=document.createElement(tag);n.textContent=text;parent.append(n);return n}
function link(parent,url,label){try{const u=new URL(url);if(u.protocol==='https:'){const a=node('a',label,parent);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer'}}catch{}}
async function session(s){adminPanel.hidden=true;$('app').hidden=true;$('login').hidden=false;for(const id of ['results','discounts','watches']) $(id).replaceChildren();if(!s)return;const {data,error}=await client.from('members').select('role').eq('user_id',s.user.id).maybeSingle();if(error||!data){status('Kontoen er ikke invitert.');await client.auth.signOut();return}$('login').hidden=true;$('app').hidden=false;status('Innlogget');adminPanel.hidden=data.role!=='admin';if(!adminPanel.hidden)refreshAdmin();await watches()}
$('loginForm').onsubmit=async e=>{e.preventDefault();const {data,error}=await client.auth.signInWithPassword({email:$('email').value,password:$('password').value});$('password').value='';if(error)fail(error);else await session(data.session)};
$('logout').onclick=async()=>{clearSuggestions();searchVersion++;await client.auth.signOut();await session(null);status('Logget ut')};
// Suggestions are from indexed offers, never invented product prices.
const qInput=$('q'), suggestionBox=document.createElement('div');
suggestionBox.id='suggestions';suggestionBox.setAttribute('aria-label','Produktforslag');
qInput.parentElement.after(suggestionBox);
let suggestTimer, suggestVersion=0, searchVersion=0;
function clearSuggestions(){clearTimeout(suggestTimer);suggestVersion++;suggestionBox.replaceChildren()}
qInput.addEventListener('input',()=>{
  clearSuggestions(); const q=qInput.value.trim(), version=suggestVersion;
  if(q.length<2)return;
  suggestTimer=setTimeout(async()=>{
    const pattern=q.replace(/[%_\\]/g,'').split(/\s+/).join('%');
    if(!pattern)return;
    const {data,error}=await client.from('offers').select('name').ilike('name','%'+pattern+'%').limit(50);
    if(version!==suggestVersion||error||$('app').hidden)return;
    for(const name of [...new Set(data.map(x=>x.name))].slice(0,8)){
      const b=node('button',name,suggestionBox);b.type='button';b.style.display='block';b.style.width='100%';b.style.textAlign='left';
      b.onclick=()=>{qInput.value=name;clearSuggestions();$('searchForm').requestSubmit()};
    }
  },300);
});
qInput.addEventListener('keydown',e=>{if(e.key==='Escape')clearSuggestions()});
$('searchForm').onsubmit=async e=>{
  e.preventDefault();clearSuggestions();const version=++searchVersion;
  try{
    const q=qInput.value.trim();if(!q)return;
    status('Søker i produktindeksen …');
    const {data,error}=await client.rpc('search_offers_v1',{q,max_results:100});
    if(error)throw error;if(version!==searchVersion||$('app').hidden)return;
    const root=$('results');root.replaceChildren();
    for(const r of data){
      const card=node('article','',root);node('strong',r.name,card);
      node('p',r.host+' · '+r.price+' kr'+(r.shipping==null?' + ukjent frakt':' · total '+r.total_price+' kr'),card);
      node('small',(r.availability||'Ukjent lagerstatus')+' · kontrollert '+new Date(r.checked).toLocaleString('nb-NO'),card);link(card,r.url,'Åpne butikk');
    }
    if(!data.length){
      const requestButton=node('button','Bestill prioritert prissøk',root);requestButton.type='button';requestButton.onclick=async()=>{requestButton.disabled=true;const result=await client.rpc('request_search_v1',{q});if(result.error){status(result.error.message);requestButton.disabled=false}else{status('Søket er lagt i kø for neste crawlerkjøring. Ingen treff er garantert.');requestButton.textContent='Søk lagt i kø'}};
      node('p','Ingen indekserte treff. Dette betyr ikke at varen ikke selges. Crawleren må finne produktet først.',root);
      const b=node('button','Lagre som prisønske',root);b.type='button';b.onclick=()=>{$('watchQuery').value=q;$('target').focus()};
    }
    status(data.length+' treff i indeksen. Ikke live-søk.');
  }catch(e){if(version===searchVersion)fail(e)}
};
$('coupons').onclick=async()=>{const {data,error}=await client.from('coupons').select('*').order('checked',{ascending:false}).limit(100);if(error)return fail(error);const root=$('discounts');root.replaceChildren();for(const r of data){const c=node('article',r.host+' · '+r.code+' · '+r.status,root);node('small',r.context||'',c);link(c,r.source,'Kilde')}};
async function watches(){const {data,error}=await client.from('watches').select('*');if(error)return fail(error);const root=$('watches');root.replaceChildren();for(const r of data){const c=node('article',r.query+' · '+r.target+' kr',root);const b=node('button','Slett',c);b.onclick=async()=>{const res=await client.from('watches').delete().eq('id',r.id);if(res.error)fail(res.error);else watches()}}}
$('watchForm').onsubmit=async e=>{e.preventDefault();const {error}=await client.from('watches').insert({query:$('watchQuery').value,target:Number($('target').value)});if(error)fail(error);else{status('Prisønske lagret (varsling er ikke aktivert ennå).');watches()}};
const adminPanel=document.createElement('section');adminPanel.hidden=true;$('app').append(adminPanel);
node('h2','Crawler og produktindeks',adminPanel);
const adminInfo=node('p','',adminPanel), runInfo=node('p','',adminPanel);
const startButton=node('button','Start indeksering',adminPanel);
const refreshButton=node('button','Oppdater status',adminPanel);
startButton.type=refreshButton.type='button';runInfo.setAttribute('role','status');runInfo.setAttribute('aria-live','polite');
const runList=node('div','',adminPanel);
let adminBusy=false;
async function crawlerRequest(method){
 const {data}=await client.auth.getSession();if(!data.session)throw Error('Logg inn på nytt');
 const r=await fetch('/api/crawler',{method,headers:{Authorization:'Bearer '+data.session.access_token},cache:'no-store',signal:AbortSignal.timeout(20000)});
 let body;try{body=await r.json()}catch{throw Error('Crawler-API svarte ikke med JSON (HTTP '+r.status+'). Kontroller Cloudflare-publiseringen.')}if(!r.ok)throw Error((body.error||'Backendfeil')+(body.github_status?' (GitHub HTTP '+body.github_status+')':''));return body;
}
async function refreshAdmin(){
 if(adminBusy)return;adminBusy=true;startButton.disabled=true;refreshButton.disabled=true;
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
  startButton.disabled=data.active;
 }catch(e){runInfo.textContent='Statusfeil: '+e.message;startButton.disabled=false}
 finally{adminBusy=false;refreshButton.disabled=false}
}
startButton.onclick=async()=>{if(adminBusy)return;adminBusy=true;startButton.disabled=true;refreshButton.disabled=true;
 runInfo.textContent='Sender startforespørsel til GitHub …';startButton.textContent='Starter …';
 let accepted=false;
 try{await crawlerRequest('POST');accepted=true;runInfo.textContent='Startforespørsel akseptert. Henter status …'}
 catch(e){runInfo.textContent='Kunne ikke starte: '+e.message}
 finally{adminBusy=false;refreshButton.disabled=false;startButton.textContent='Start indeksering';startButton.disabled=accepted}
 if(accepted)setTimeout(refreshAdmin,3000)
};
refreshButton.onclick=refreshAdmin;
const {data}=await client.auth.getSession();await session(data.session);client.auth.onAuthStateChange((event)=>{if(event==='SIGNED_OUT'){ adminPanel.hidden=true; $('app').hidden=true;$('login').hidden=false;for(const id of ['results','discounts','watches'])$(id).replaceChildren()}});
