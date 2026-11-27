import {githubHeaders} from '../lib/github-app.js';
const repo='https://api.github.com/repos/tebendheim/Prisradar/actions/workflows/crawl.yml';
const json=(data,status=200)=>Response.json(data,{status,headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}});
export async function onRequest({request,env}){
 try{
 const method=request.method;
 if(!['GET','POST'].includes(method))return json({error:'Method not allowed'},405);
 if(!env.SUPABASE_URL||!env.SUPABASE_PUBLISHABLE_KEY)return json({error:'Supabase-konfigurasjon mangler i Cloudflare'},503);
 const auth=request.headers.get('Authorization');
 if(!auth?.startsWith('Bearer '))return json({error:'Logg inn'},401);
 if(method==='POST'&&request.headers.get('Origin')!==new URL(request.url).origin)return json({error:'Ugyldig opprinnelse'},403);
 const headers={apikey:env.SUPABASE_PUBLISHABLE_KEY,Authorization:auth};
 const u=await fetch(env.SUPABASE_URL+'/auth/v1/user',{headers});
 if(!u.ok)return json({error:'Ugyldig sesjon'},401);
 const user=await u.json();
 const m=await fetch(env.SUPABASE_URL+'/rest/v1/members?select=role&user_id=eq.'+encodeURIComponent(user.id),{headers});
 if(!m.ok||!(await m.json()).some(x=>x.role==='admin'))return json({error:'Kun administrator'},403);
 const healthResponse=await fetch(env.SUPABASE_URL+'/rest/v1/rpc/schema_health_v1',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:'{}'});
 const health=healthResponse.ok?await healthResponse.json():{ready:false,version:0,missing:['schema_health_v1 utilgjengelig (HTTP '+healthResponse.status+')']};
 const ready=health.ready===true&&health.version>=2026112701;
 if(method==='POST'&&!ready)return json({error:'Databasen må oppdateres: supabase/migrations/2026112701.sql',health},503);
 let gh;try{gh=await githubHeaders(env)}catch(e){return json({error:e.message.startsWith('GitHub')?e.message:'GitHub App-nøkkelen kunne ikke leses'},503)}
 const r=await fetch(repo+'/runs?per_page=10',{headers:gh});
 if(!r.ok)return json({error:'GitHub kunne ikke lese kjøringer',github_status:r.status},502);
 const runs=(await r.json()).workflow_runs||[];
 const active=runs.some(x=>x.status!=='completed');
 if(method==='GET')return json({active,health:{...health,ready},runs:runs.map(x=>({id:x.id,status:x.status,conclusion:x.conclusion,created_at:x.created_at,updated_at:x.updated_at}))});
 if(active)return json({error:'Crawleren kjører allerede'},409);
 let extra=false;try{const body=await request.json();extra=body.extra===true}catch{}
 const reservation=await fetch(env.SUPABASE_URL+'/rest/v1/rpc/reserve_crawl_v2',{method:'POST',headers:{...headers,'Content-Type':'application/json'},body:JSON.stringify({extra})});
 if(!reservation.ok)return json({error:'Kjør SQL-migreringen for crawlerstyring først'},503);
 if(await reservation.json()!==true)return json({error:'Kjørekvote nådd eller ett minutts ventetid. Se kvoteoversikten.'},429);
 const d=await fetch(repo+'/dispatches',{method:'POST',headers:{...gh,'Content-Type':'application/json'},body:JSON.stringify({ref:'main'})});
 if(!d.ok)return json({error:'GitHub avviste starten',github_status:d.status},502);
 return json({accepted:true},202);
 }catch{return json({error:'Kunne ikke kontakte backend'},502)}
}
