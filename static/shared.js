const $=id=>document.getElementById(id);
const S={get scope(){try{return localStorage.getItem('scope')||'nasa'}catch(e){return'nasa'}},set scope(v){try{localStorage.setItem('scope',v)}catch(e){}},
 get region(){try{return localStorage.getItem('region')||'in-pb-hr'}catch(e){return'in-pb-hr'}},set region(v){try{localStorage.setItem('region',v)}catch(e){}}};
async function api(path,opts){let r;try{r=await fetch(path,opts)}catch(e){throw new Error('Could not reach AgniLens. Check that the server is running and try again.')}
 let j={};try{j=await r.json()}catch(e){}if(!r.ok)throw new Error(j.error||r.status+' '+r.statusText);return j}
function qs(o){return new URLSearchParams(Object.entries(Object.assign({scope:S.scope,region:S.region},o||{})).filter(([,v])=>v!==''&&v!=null)).toString()}
const ICONS={
 overview:'<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5M9 21v-7h6v7"/>',
 map:'<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15m6-12v15"/>',
 data:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/>',
 calendar:'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 17h.01M12 17h.01"/>',
 compare:'<path d="M7 7h13l-3-3M17 17H4l3 3"/><path d="M20 7v6M4 17v-6"/>',
 harmonize:'<circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="m8 7 7 9M18 6h.01M6 18h.01"/>',
 anomalies:'<path d="M12 3 2.8 20h18.4L12 3Z"/><path d="M12 9v5m0 3h.01"/>',
 regional:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18"/>',
 reports:'<path d="M6 3h9l4 4v14H6z"/><path d="M14 3v5h5M9 12h7M9 16h7"/>',
 experimental:'<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/><path d="M8 15h8"/>',
 help:'<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.6 2.6 0 1 1 4.8 1.4c-1.2 1.2-2.3 1.4-2.3 3.1m0 3h.01"/>'
};
const icon=k=>'<svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+ICONS[k]+'</svg>';
const PAGES=[['/','Overview','overview'],['/map','Global Map','map'],['/harmonize','Harmonization','harmonize'],['/data','Data Explorer','data'],['/calendar','Calendar','calendar'],['/compare','Compare','compare'],['/anomalies','Anomalies','anomalies'],['/regional','Regional Analytics','regional'],['/reports','Reports','reports'],['/experimental','Experimental','experimental']];
function setSidebar(open){document.body.classList.toggle('sidebar-open',open);const b=$('mobileNav');if(b)b.setAttribute('aria-expanded',String(open));const scrim=$('sidebarScrim');if(scrim)scrim.hidden=!open}
async function shell(){
 const regs=await api('/api/regions');window.AGNILENS_REGIONS=regs;
 const path=location.pathname,main=document.querySelector('.wrap');if(main)main.id=main.id||'main-content';
 const nav=PAGES.map(p=>'<a class="side-link'+(p[0]===path?' active':'')+'" href="'+p[0]+'" title="'+p[1]+'" '+(p[0]===path?'aria-current="page"':'')+'><span class="side-icon">'+icon(p[2])+'</span><span class="side-label">'+p[1]+'</span></a>').join('');
 document.body.classList.add('app-body');
 document.body.insertAdjacentHTML('afterbegin','<a class="skip-link" href="#main-content">Skip to content</a><div id="sidebarScrim" class="sidebar-scrim" hidden></div><aside class="sidebar" id="app-sidebar" aria-label="Application sidebar"><div class="side-brand"><a href="/" aria-label="AgniLens overview"><span class="brand-mark">A</span><span class="side-label">AgniLens</span></a><button id="collapseNav" class="icon-button collapse-button" type="button" aria-label="Collapse sidebar" title="Collapse sidebar"><span aria-hidden="true">‹</span></button></div><nav class="side-nav" aria-label="Main navigation">'+nav+'</nav><div class="side-footer"><a class="side-link" href="/data#nrt-section" title="Help and settings"><span class="side-icon">'+icon('help')+'</span><span class="side-label">Help &amp; Settings</span></a><div class="side-footnote side-label">Satellite detections · not individual fires</div></div></aside><header class="app-topbar"><button id="mobileNav" class="icon-button mobile-menu" type="button" aria-label="Open navigation menu" aria-expanded="false" aria-controls="app-sidebar"><span aria-hidden="true">☰</span></button><div class="topbar-context"><span class="eyebrow">GEOSPATIAL MONITORING</span><strong id="pageTitle">'+esc(main&&main.querySelector('h1')?main.querySelector('h1').textContent:'AgniLens')+'</strong></div><div class="topbar-filters"><label class="top-filter"><span>Data scope</span><select id="scopeSel" aria-label="Data scope"><option value="nasa">NASA observations</option><option value="demo">Synthetic demo</option></select></label><label class="top-filter region-filter"><span>Region</span><select id="regSel" aria-label="Study region">'+regs.map(r=>'<option value="'+esc(r.id)+'">'+esc(r.name)+'</option>').join('')+'</select></label><a class="topbar-help" href="/data#nrt-section" title="Help and data sources" aria-label="Help and data sources">?</a></div></header><div id="banner" class="scope-banner" role="status" aria-live="polite"></div>');
 let collapsed=false;try{collapsed=localStorage.getItem('sidebar-collapsed')==='1'}catch(e){}document.body.classList.toggle('sidebar-collapsed',collapsed);
 $('scopeSel').value=S.scope;$('regSel').value=S.region;
 $('scopeSel').onchange=e=>{S.scope=e.target.value;location.reload()};$('regSel').onchange=e=>{S.region=e.target.value;location.reload()};
 const collapse=$('collapseNav');collapse.setAttribute('aria-expanded',String(!collapsed));collapse.onclick=()=>{const next=!document.body.classList.contains('sidebar-collapsed');document.body.classList.toggle('sidebar-collapsed',next);collapse.setAttribute('aria-expanded',String(!next));collapse.setAttribute('aria-label',next?'Expand sidebar':'Collapse sidebar');collapse.title=next?'Expand sidebar':'Collapse sidebar';try{localStorage.setItem('sidebar-collapsed',next?'1':'0')}catch(e){}};
 $('mobileNav').onclick=()=>setSidebar(!document.body.classList.contains('sidebar-open'));$('sidebarScrim').onclick=()=>setSidebar(false);document.addEventListener('keydown',e=>{if(e.key==='Escape')setSidebar(false)});document.querySelectorAll('.side-link').forEach(a=>a.addEventListener('click',()=>setSidebar(false)));
 $('banner').className='scope-banner '+(S.scope==='demo'?'b-demo':'b-nasa');$('banner').textContent=S.scope==='demo'?'SYNTHETIC DEMO DATA · Separate from NASA observations':'NASA DATA SCOPE · Live FIRMS or user-imported archive observations';
 return regs;
}
async function withBusy(button,action){if(button.disabled)return;button.disabled=true;button.setAttribute('aria-busy','true');try{return await action()}finally{button.disabled=false;button.removeAttribute('aria-busy')}}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const chip=o=>'<span class="chip '+(o==='demo'?'c-demo':'c-nasa')+'">'+({demo:'synthetic demo',nasa_nrt:'NASA live NRT',nasa_archive:'NASA archive import'}[o]||o)+'</span>';
const EMPTY='<div class="card onboarding-empty"><b>No observations in this selected scope and region.</b><p class="muted">Go to <a href="/data">Data Explorer</a> to retrieve NASA FIRMS data, import a real archive, or load the clearly labelled synthetic demo. No activity is drawn when observations are unavailable.</p></div>';
