const $=id=>document.getElementById(id);
const S={get scope(){try{return localStorage.getItem('scope')||'nasa'}catch(e){return'nasa'}},set scope(v){try{localStorage.setItem('scope',v)}catch(e){}},
 get region(){try{return localStorage.getItem('region')||'in-pb-hr'}catch(e){return'in-pb-hr'}},set region(v){try{localStorage.setItem('region',v)}catch(e){}}};
async function api(path,opts){let r;try{r=await fetch(path,opts)}catch(e){throw new Error('Could not reach AgniLens. Check that the server is running and try again.')}
 let j={};try{j=await r.json()}catch(e){}if(!r.ok)throw new Error(j.error||`${r.status} ${r.statusText}`);return j}
function qs(o){return new URLSearchParams(Object.entries({scope:S.scope,region:S.region,...(o||{})}).filter(([,v])=>v!==''&&v!=null)).toString()}
const PAGES=[['/','Overview'],['/map','Map'],['/harmonize','Harmonization'],['/calendar','Calendar'],['/compare','MODIS vs VIIRS'],['/regional','Regions'],['/anomalies','Anomalies'],['/data','Data'],['/reports','Reports'],['/experimental','Experimental']];
async function shell(){
 const regs=await api('/api/regions');
 const path=location.pathname;
 const main=document.querySelector('.wrap');if(main)main.id=main.id||'main-content';
 document.body.insertAdjacentHTML('afterbegin','<a class="skip-link" href="#main-content">Skip to content</a><nav class="nav" aria-label="Main navigation"><div class="in"><a class="brand" href="/">Agni<span>Lens</span></a>'+
  PAGES.map(p=>'<a class="l'+(p[0]===path?' on':'')+'" '+(p[0]===path?'aria-current="page" ':'')+'href="'+p[0]+'">'+p[1]+'</a>').join('')+'<span class="sp"></span>'+
  '<select id="scopeSel" aria-label="Data scope"><option value="nasa">NASA data</option><option value="demo">Demo (synthetic)</option></select>'+
  '<select id="regSel" aria-label="Region">'+regs.map(r=>'<option value="'+esc(r.id)+'">'+esc(r.name)+'</option>').join('')+'</select></div></nav>'+
  '<div id="banner"></div>');
 $('scopeSel').value=S.scope;$('regSel').value=S.region;
 $('scopeSel').onchange=e=>{S.scope=e.target.value;location.reload()};$('regSel').onchange=e=>{S.region=e.target.value;location.reload()};
 $('banner').className=S.scope==='demo'?'b-demo':'b-nasa';
 $('banner').textContent=S.scope==='demo'?'DEMONSTRATION DATA: synthetic observations, not NASA data.':'Showing NASA FIRMS data you have retrieved (live NRT) or imported (archive exports).';
 return regs;
}
async function withBusy(button, action){if(button.disabled)return;button.disabled=true;button.setAttribute('aria-busy','true');try{return await action()}finally{button.disabled=false;button.removeAttribute('aria-busy')}}
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const chip=o=>'<span class="chip '+(o==='demo'?'c-demo':'c-nasa')+'">'+({demo:'synthetic demo',nasa_nrt:'NASA live NRT',nasa_archive:'NASA archive import'}[o]||o)+'</span>';
const EMPTY='<div class="card"><b>No data loaded for this scope yet.</b><p class="muted">Go to <a href="/data">Data</a> to retrieve live NASA observations, import a FIRMS archive export, or load the clearly labelled synthetic demo dataset.</p></div>';
