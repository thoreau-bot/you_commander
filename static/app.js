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
  if(e.key=='Enter'||e.key==' '){if(/^(BUTTON|SUMMARY)$/.test(a.tagName))return true;if(a.tagName=='A'&&e.key=='Enter')return true;if(a.tagName=='INPUT'&&a.type=='checkbox')return true}
  return false};
 // Esc has levels: a focused control gives focus back first; then a page closes its transients; only from rest does it leave.
 yc.escapeControl=e=>{const a=document.activeElement;if(!a||a===document.body||yc.typing(a))return false;if(a.blur){a.blur();e.preventDefault();return true}return false};
 yc.isControl=el=>!!el&&el!==document.body&&(/^(BUTTON|A|SUMMARY|INPUT|SELECT|TEXTAREA)$/.test(el.tagName)||el.tabIndex>=0);

 // ---- status / toast ----
 let T=null;
 function toastEl(){let t=document.getElementById('toast');if(!t){t=document.createElement('div');t.id='toast';document.body.appendChild(t)}
  if(!t.getAttribute('role')){t.setAttribute('role','status');t.setAttribute('aria-live','polite')}return t}
 yc.toast=(msg,ms)=>{const t=toastEl();t.textContent=msg;t.style.display='block';clearTimeout(T);T=setTimeout(()=>{t.style.display='none'},ms||2600)};

 // ---- popovers (replace prompt/confirm/alert) ----
 let POP=null;
 function closePop(result){if(!POP)return;const {el,resolve,prev}=POP;POP=null;el.remove();document.removeEventListener('mousedown',onDoc,true);
  try{prev&&prev.focus&&prev.focus()}catch(e){}resolve(result)}
 function onDoc(e){if(POP&&!POP.el.contains(e.target))closePop(POP.cancel)}
 function place(el,anchor){document.body.appendChild(el);const r=anchor&&anchor.getBoundingClientRect?anchor.getBoundingClientRect():{left:innerWidth/2-160,bottom:innerHeight/2-60,top:innerHeight/2-60,width:0};
  const w=el.offsetWidth,h=el.offsetHeight;let x=Math.max(8,Math.min(innerWidth-w-8,r.left)),y=r.bottom+6;if(y+h>innerHeight-8)y=Math.max(8,r.top-h-6);el.style.left=x+'px';el.style.top=y+'px'}
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
