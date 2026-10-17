// YouCommander — shared page behaviour.
//  yc.typing(el)      true when el takes text (so letter shortcuts must not fire)
//  yc.onControl(e)    true when Enter/Space should go to the focused button/link/summary/checkbox, not to the page
//  yc.toast(msg, ms)  status line that nothing else overwrites (role=status, aria-live)
//  yc.confirm(opts)   popover confirm  -> Promise<bool>     { anchor, message, ok, danger }
//  yc.prompt(opts)    popover text box -> Promise<string|null> { anchor, label, value, ok }
//  ? opens the shortcuts overlay (#help) on every page.
(function(){
 const yc=window.yc={};
 yc.typing=el=>!!el&&(el.tagName=='TEXTAREA'||el.tagName=='SELECT'||(el.tagName=='INPUT'&&el.type!='checkbox')||el.isContentEditable);
 yc.onControl=e=>{const a=document.activeElement;if(!a||a===document.body)return false;
  if(e.key=='Enter'||e.key==' '){if(/^(BUTTON|SUMMARY)$/.test(a.tagName))return true;if(a.tagName=='A'&&e.key=='Enter')return true;
   if(a.tagName=='INPUT'&&a.type=='checkbox'){if(e.key=='Enter'){e.preventDefault();a.click()}return true}}
  return false};
 // Esc has levels: a focused control gives focus back first; then a page closes its transients; only from rest does it leave.
 yc.escapeControl=e=>{const a=document.activeElement;if(!a||a===document.body||(yc.typing(a)&&a.tagName!='SELECT'))return false;if(a.blur){a.blur();e.preventDefault();return true}return false};
 addEventListener('keydown',e=>{const a=document.activeElement;if(e.key=='Escape'&&a&&a.tagName=='SELECT'&&!e.ctrlKey&&!e.metaKey){e.preventDefault();e.stopImmediatePropagation();a.blur()}},true);
 // a mouse click on a button or checkbox hands focus straight back, so the keyboard keeps meaning what the screen says
 document.addEventListener('mouseup',e=>{if(!(e.target instanceof Element))return;const b=e.target.closest('button,summary,input[type=checkbox],.row a');if(!b||b.closest('.pop')||b.closest('#help'))return;setTimeout(()=>{if(document.activeElement===b)b.blur()},0)});
 // the embedded player has focus: say so, since the app's keys are off while it does
 let IFT=null;addEventListener('blur',()=>{setTimeout(()=>{if(document.activeElement&&document.activeElement.tagName=='IFRAME'){IFT=yc.toast('The video has focus, so YouTube’s own keys apply. Click outside it or Tab past its controls to get the app shortcuts back.',60000)}},0)});
 addEventListener('focus',()=>{if(IFT){yc.toastHide();IFT=null}});
 // sentinels around an embedded player: focus arriving by Tab passes through; focus returning from the iframe lands on the next real control
 const FOC='a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),iframe,[tabindex]:not([tabindex="-1"])';
 const visible=el=>!!(el.offsetWidth||el.offsetHeight||el.getClientRects().length);
 yc.sentinel=(el,onReturn)=>{el.tabIndex=0;el.addEventListener('focus',e=>{
  const order=[...document.querySelectorAll(FOC)].filter(visible);const i=order.indexOf(el),j=order.indexOf(e.relatedTarget);
  const fromFrame=!!(e.relatedTarget&&e.relatedTarget.tagName=='IFRAME');const fwd=j<0?true:j<i;
  if(fromFrame&&onReturn)onReturn();
  let t=null;const ok=x=>!x.classList.contains('pwret')&&!(fromFrame&&x.tagName=='IFRAME');
  if(fwd){for(let k=i+1;k<order.length;k++)if(ok(order[k])){t=order[k];break}}else{for(let k=i-1;k>=0;k--)if(ok(order[k])){t=order[k];break}}
  if(t)t.focus({preventScroll:true});else el.blur()})};
 yc.isControl=el=>!!el&&el!==document.body&&(/^(BUTTON|A|SUMMARY|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)||el.tabIndex>=0);

 // ---- status / toast ----
 let T=null;
 function toastEl(){let t=document.getElementById('toast');if(!t){t=document.createElement('div');t.id='toast';document.body.appendChild(t)}
  if(!t.getAttribute('role')){t.setAttribute('role','status');t.setAttribute('aria-live','polite')}return t}
 let UNDO=null;
 yc.toast=(msg,ms,o)=>{const t=toastEl();t.textContent='';UNDO=null;
  if(o&&o.undo){UNDO=o.undo;t.append(msg+' ');const b=document.createElement('button');b.className='sm';b.innerHTML='Undo<kbd>Z</kbd>';b.onclick=()=>{const f=UNDO;yc.toastHide();f&&f()};t.appendChild(b)}else t.textContent=msg;
  t.style.display='block';clearTimeout(T);T=setTimeout(()=>{yc.toastHide()},ms||2600);return true};
 yc.toastHide=()=>{const t=toastEl();t.style.display='none';UNDO=null};
 addEventListener('keydown',e=>{if(UNDO&&(e.key=='z'||e.key=='Z')&&!e.ctrlKey&&!e.metaKey&&!e.altKey&&!yc.typing(document.activeElement)){e.preventDefault();e.stopImmediatePropagation();const f=UNDO;yc.toastHide();f()}},true);

 // ---- popovers (replace prompt/confirm/alert) ----
 let POP=null;
 function closePop(result){if(!POP)return;const {el,resolve,prev}=POP;POP=null;el.remove();document.removeEventListener('mousedown',onDoc,true);
  try{prev&&prev.focus&&prev.focus()}catch(e){}resolve(result)}
 function onDoc(e){if(POP&&!POP.el.contains(e.target))closePop(POP.cancel)}
 function place(el,anchor){document.body.appendChild(el);const r=anchor&&anchor.getBoundingClientRect?anchor.getBoundingClientRect():{left:innerWidth/2-160,bottom:innerHeight/2-60,top:innerHeight/2-60,width:0};
  const w=el.offsetWidth,h=el.offsetHeight;let x=Math.max(8,Math.min(innerWidth-w-8,r.left)),y=r.bottom+8;el.classList.remove('up');if(y+h>innerHeight-8){y=Math.max(8,r.top-h-8);el.classList.add('up')}el.style.left=x+'px';el.style.top=y+'px'}
 function open(el,anchor,resolve,cancel){if(POP)closePop(POP.cancel);POP={el,resolve,prev:document.activeElement,cancel};place(el,anchor);document.addEventListener('mousedown',onDoc,true)}
 yc.confirm=o=>new Promise(res=>{const el=document.createElement('div');el.className='pop';el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');
  el.innerHTML=`<div class=pop-msg></div><div class=pop-acts><button class=ghost data-a=no>Cancel<kbd>Esc</kbd></button><button class="${o.danger?'bad':'pri'}" data-a=ok></button></div>`;
  el.querySelector('.pop-msg').textContent=o.message;el.querySelector('[data-a=ok]').innerHTML=(o.ok||'OK')+'<kbd>Enter</kbd>';
  el.onclick=e=>{const b=e.target.closest('[data-a]');if(b)closePop(b.dataset.a=='ok')};
  el.onkeydown=e=>{e.stopPropagation();if(e.key=='Escape'){e.preventDefault();closePop(false)}else if(e.key=='Enter'){e.preventDefault();closePop(true)}else if(e.key=='Tab')cycle(el,e)};
  open(el,o.anchor,res,false);el.querySelector('[data-a=ok]').focus()});
 function cycle(el,e){const f=[...el.querySelectorAll('button,input')];if(!f.length)return;const i=f.indexOf(document.activeElement);const n=e.shiftKey?(i<=0?f.length-1:i-1):(i<0||i==f.length-1?0:i+1);e.preventDefault();f[n].focus()}
 yc.prompt=o=>new Promise(res=>{const el=document.createElement('div');el.className='pop';el.setAttribute('role','dialog');el.setAttribute('aria-modal','true');
  el.innerHTML=`<label class=pop-msg><span></span><input type=text autocomplete=off></label><div class=pop-acts><button class=ghost data-a=no>Cancel<kbd>Esc</kbd></button><button class=pri data-a=ok></button></div>`;
  el.querySelector('span').textContent=o.label;const inp=el.querySelector('input');inp.value=o.value||'';el.querySelector('[data-a=ok]').innerHTML=(o.ok||'Save')+'<kbd>Enter</kbd>';
  const done=ok=>closePop(ok?inp.value.trim()||null:null);
  el.onclick=e=>{const b=e.target.closest('[data-a]');if(b)done(b.dataset.a=='ok')};
  el.onkeydown=e=>{e.stopPropagation();if(e.key=='Escape'){e.preventDefault();done(false)}else if(e.key=='Enter'){e.preventDefault();done(true)}else if(e.key=='Tab')cycle(el,e)};
  open(el,o.anchor,res,null);inp.focus();inp.select()});
 yc.popOpen=()=>!!POP;
 yc.busy=fn=>{let on=false;return async function(...a){if(on)return;on=true;try{return await fn.apply(this,a)}finally{on=false}}};
 // transients: things Esc closes before a page may act on Esc itself (register as {open:()=>bool, close:()=>void})
 const TR=[];yc.transient=t=>TR.push(t);yc.closeTransient=()=>{for(const t of TR){try{if(t.open()){t.close();return true}}catch(e){}}return false};

 // ---- tag picker: prefix match on paths, create-if-missing, arrows, Enter picks only a visible choice, Esc = close list -> clear -> leave ----
 yc.tagPicker=(input,list,o)=>{let sel=0;const norm=q=>q.trim().replace(/\s*\/\s*/g,' / ').toLowerCase();
  const matches=q=>{q=norm(q);const T=o.tags();return T.filter(t=>t.name!='Inbox'&&o.pathOf(t).toLowerCase().includes(q)).sort((a,b)=>(o.pathOf(a).toLowerCase().startsWith(q)?0:1)-(o.pathOf(b).toLowerCase().startsWith(q)?0:1)||(b.n||0)-(a.n||0)).slice(0,12)};
  const opts=()=>{const q=input.value.trim();if(!q)return[];const m=matches(q);const nq=norm(q);if(o.create!==false&&!o.tags().some(t=>o.pathOf(t).toLowerCase()==nq||t.name.toLowerCase()==q.toLowerCase()))m.push({create:1,name:q});return m};
  let armed=false;   // the Create row is chosen by Enter only after an explicit ↓ onto it, or when the query is a path
  const createArmed=()=>armed||input.value.includes('/');
  const esc=x=>(x||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const draw=()=>{const m=opts();const show=!!input.value.trim()&&m.length>0;list.style.display=show?'block':'none';input.setAttribute('aria-expanded',show?'true':'false');
   list.innerHTML=m.map((t,k)=>t.create?`<div role=option class="${k==sel?'on':''}" data-new="1"><b>+ Create tag</b> “${esc(t.name.split('/').map(x=>x.trim()).filter(Boolean).join(' › '))}”</div>`:`<div role=option class="${k==sel?'on':''}" data-id=${t.id} title="${esc(t.description||'')}">${esc(o.pathOf(t))} <span class=mut>${t.n??''}</span></div>`).join('')};
  const close=()=>{list.style.display='none';input.setAttribute('aria-expanded','false')};
  const choose=async t=>{close();let v;if(t.create){v=await o.onCreate(t.name)}else v=await o.onPick(t.id);input.value=typeof v=='string'?v:'';sel=0;close()};
  input.setAttribute('role','combobox');input.setAttribute('aria-autocomplete','list');list.setAttribute('role','listbox');
  input.addEventListener('input',()=>{sel=0;armed=false;draw()});
  input.addEventListener('keydown',e=>{const m=opts(),open=list.style.display=='block';
   if(e.key=='ArrowDown'&&open){e.preventDefault();e.stopPropagation();sel=Math.min(m.length-1,sel+1);armed=true;draw()}
   else if(e.key=='ArrowUp'&&open){e.preventDefault();e.stopPropagation();sel=Math.max(0,sel-1);draw()}
   else if(e.key=='Enter'){if(!open&&input.value.trim()&&o.onEnter&&o.onEnter()){e.preventDefault();e.stopPropagation();return}e.preventDefault();e.stopPropagation();if(open&&m[sel]&&(!m[sel].create||createArmed())){choose(m[sel])}else if(!input.value.trim())input.blur();else if(open&&m[sel]&&m[sel].create){yc.toast('No existing tag matches “'+input.value.trim()+'”. Press ↓ then Enter to create it.',3200)}else{yc.toast('No tag matches that; keep typing')}}
   else if(e.key=='Escape'){e.preventDefault();e.stopPropagation();if(open)close();else if(input.value){input.value='';draw()}else input.blur()}
   else if(e.key=='Tab')close()});
  input.addEventListener('blur',()=>setTimeout(()=>{if(document.activeElement!==input)close()},120));
  list.addEventListener('mousedown',e=>{const d=e.target.closest('[data-id],[data-new]');if(!d)return;e.preventDefault();d.dataset.new?choose({create:1,name:input.value.trim()}):choose({id:+d.dataset.id})});
  return {close,draw}};

 // ---- keyboard help overlay ----
 const h=document.getElementById('help');
 if(h){
  h.setAttribute('role','dialog');h.setAttribute('aria-modal','true');h.setAttribute('aria-label','Keyboard shortcuts');
  const card=h.querySelector('.card');if(card){card.tabIndex=-1;if(!card.querySelector('.pop-close')){const b=document.createElement('button');b.className='ghost sm pop-close';b.setAttribute('aria-label','Close');b.innerHTML='Close<kbd>Esc</kbd>';b.onclick=()=>openHelp(false);card.querySelector('h2')?.appendChild(b)}}
  let prev=null;
  const openHelp=o=>{const was=h.classList.contains('open');h.classList.toggle('open',o);if(o&&!was){prev=document.activeElement;card&&card.focus({preventScroll:true})}if(!o&&was){try{if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();if(prev&&prev!==document.body&&prev.isConnected&&!/pop-close/.test(prev.className))prev.focus()}catch(e){}}};
  window.toggleHelp=()=>openHelp(!h.classList.contains('open'));
  addEventListener('keydown',e=>{
   if(h.classList.contains('open')){
    if(e.key=='Escape'||e.key=='?'){e.preventDefault();e.stopImmediatePropagation();openHelp(false)}
    else if(e.key=='Tab'){/* keep focus inside */const f=[...card.querySelectorAll('button,[tabindex="0"]')];if(f.length){const i=f.indexOf(document.activeElement);const n=e.shiftKey?(i<=0?f.length-1:i-1):(i<0||i==f.length-1?0:i+1);e.preventDefault();f[n].focus()}}
    else if(!yc.typing(document.activeElement)&&!e.ctrlKey&&!e.metaKey){e.preventDefault();e.stopImmediatePropagation()}
    return}
   if(e.key=='?'&&!yc.typing(document.activeElement)&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();e.stopImmediatePropagation();openHelp(true)}
  },true);
  h.addEventListener('click',e=>{if(e.target===h)openHelp(false)});
  document.querySelectorAll('[data-help]').forEach(b=>{b.setAttribute('aria-label','Keyboard shortcuts');b.addEventListener('click',()=>{openHelp(true)})});
 }
 // a popover swallows page shortcuts while it is open
 addEventListener('keydown',e=>{if(POP&&!POP.el.contains(e.target)){if(e.key=='Escape')closePop(POP.cancel);else if(e.key=='Enter'){const ok=POP.el.querySelector('[data-a=ok]');ok&&ok.click()}else if(e.key=='Tab'){cycle(POP.el,e)}e.stopImmediatePropagation();e.preventDefault()}},true);
 // status nodes announce politely
 if(!document.documentElement.lang)document.documentElement.lang='en';
 document.querySelectorAll('#info,#vs,#st,#pos,#toast').forEach(el=>{if(!el.getAttribute('role')){el.setAttribute('role','status');el.setAttribute('aria-live','polite')}});
})();
