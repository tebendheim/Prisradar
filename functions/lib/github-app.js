// GitHub App installation authentication. Private key stays in Pages Functions.
const enc=new TextEncoder();
const b64url=bytes=>btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/=/g,'').replace(/\+/g,'-').replace(/\//g,'_');
function derLen(n){if(n<128)return [n];const a=[];while(n){a.unshift(n&255);n=Math.floor(n/256)}return [128|a.length,...a]}
function der(tag,bytes){return Uint8Array.from([tag,...derLen(bytes.length),...bytes])}
function privateKeyBytes(pem){
 const normalized=pem.trim().replace(/\\n/g,'\n');
 const pkcs1=normalized.includes('-----BEGIN RSA PRIVATE KEY-----');
 if(!pkcs1&&!normalized.includes('-----BEGIN PRIVATE KEY-----'))throw Error('Invalid PEM');
 const raw=Uint8Array.from(atob(normalized.replace(/-----[^-]+-----/g,'').replace(/\s/g,'')),c=>c.charCodeAt(0));
 if(!pkcs1)return raw;
 // Wrap PKCS#1 in PKCS#8 for Web Crypto.
 return der(48,Uint8Array.from([2,1,0,48,13,6,9,42,134,72,134,247,13,1,1,1,5,0,...der(4,raw)]));
}
export async function githubHeaders(env){
 const id=env.GITHUB_APP_ID, installation=env.GITHUB_INSTALLATION_ID;
 if(!/^\d+$/.test(id||'')||!/^\d+$/.test(installation||'')||!env.GITHUB_APP_PRIVATE_KEY)throw Error('GitHub App-konfigurasjon mangler');
 const now=Math.floor(Date.now()/1000);
 const unsigned=b64url(enc.encode(JSON.stringify({alg:'RS256',typ:'JWT'})))+'.'+b64url(enc.encode(JSON.stringify({iat:now-60,exp:now+540,iss:id})));
 const key=await crypto.subtle.importKey('pkcs8',privateKeyBytes(env.GITHUB_APP_PRIVATE_KEY),{name:'RSASSA-PKCS1-v1_5',hash:'SHA-256'},false,['sign']);
 const sig=await crypto.subtle.sign('RSASSA-PKCS1-v1_5',key,enc.encode(unsigned));
 const base={Accept:'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'PrisRadar'};
 const res=await fetch('https://api.github.com/app/installations/'+installation+'/access_tokens',{method:'POST',headers:{...base,Authorization:'Bearer '+unsigned+'.'+b64url(sig),'Content-Type':'application/json'},body:JSON.stringify({repositories:['Prisradar'],permissions:{actions:'write'}})});
 if(!res.ok)throw Error('GitHub App-autentisering feilet (HTTP '+res.status+')');
 const body=await res.json();if(!body.token)throw Error('GitHub returnerte ingen tilgangsnøkkel');
 return {...base,Authorization:'Bearer '+body.token};
}
