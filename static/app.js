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
 // the embedded player took the keyboard (a click or Tab into it). On pages with video controls (F) the player mode
 // decides what happens; elsewhere, say so, since the app's keys are off while it has focus.
 let IFT=null;addEventListener('blur',()=>{setTimeout(()=>{const a=document.activeElement;if(!a||a.tagName!='IFRAME')return;
  if(PM){PM.frameFocused(a);return}
  IFT=yc.toast('The video has focus, so YouTube’s own keys apply. Click outside it or Tab past its controls to get the app shortcuts back.',60000)},0)});
 addEventListener('focus',()=>{if(PM)PM.pageFocused();if(IFT){yc.toastHide();IFT=null}});
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

 // ---- bubbles (bottom right): one standing hint (the video-controls card) and transient toasts.
 //      A toast takes the hint's place for a while; with a hint standing, no toast stays longer than 10-15 s
 //      (by length), and when it goes the hint comes back in whatever state it is in by then.
 let T=null,TON=false,TEND=0,TLEN=0,HINT=null;
 function toastEl(){let t=document.getElementById('toast');if(!t){t=document.createElement('div');t.id='toast';document.body.appendChild(t)}
  if(!t.getAttribute('role')){t.setAttribute('role','status');t.setAttribute('aria-live','polite')}return t}
 function hintEl(){let h=document.getElementById('fhint');if(!h){h=document.createElement('div');h.id='fhint';document.body.appendChild(h)}return h}
 const capFor=n=>10000+5000*Math.max(0,Math.min(1,(n-60)/140));   // 10 s for a short line, up to 15 s for a long one
 function paint(){const h=hintEl(),t=toastEl();t.style.display=TON?'block':'none';
  const ht=!TON&&HINT?(typeof HINT=='function'?HINT():HINT):null;if(ht){if(h.innerHTML!==ht)h.innerHTML=ht;h.style.display='block'}else h.style.display='none'}
 function arm(ms){clearTimeout(T);TEND=Date.now()+ms;T=setTimeout(()=>{yc.toastHide()},ms)}
 let UNDO=null;
 yc.toast=(msg,ms,o)=>{const t=toastEl();t.textContent='';UNDO=null;
  if(o&&o.undo){UNDO=o.undo;t.append(msg+' ');const b=document.createElement('button');b.className='sm';b.innerHTML='Undo<kbd>Z</kbd>';b.onclick=()=>{const f=UNDO;yc.toastHide();f&&f()};t.appendChild(b)}else t.textContent=msg;
  TON=true;TLEN=String(msg).length;let d=ms||2600;if(HINT)d=Math.min(d,capFor(TLEN));arm(d);paint();return true};
 yc.toastHide=()=>{clearTimeout(T);TON=false;UNDO=null;paint()};
 // hint: a string, or a function giving the current text (HTML), or null to clear. Showing it dismisses a plain
 // status toast at once (the user just asked for the hint); an undo toast stays on top but is held to the cap.
 yc.hint=src=>{const was=!!HINT;HINT=src||null;if(HINT&&!was&&TON){if(UNDO){const left=TEND-Date.now(),c=capFor(TLEN);if(left>c)arm(c)}else{clearTimeout(T);TON=false}}paint()};
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

 // ---- video controls (F): keys drive an embedded video through the YouTube API while the keyboard stays with the page.
 //      Esc is the only way out. F or Enter = fullscreen, as inside YouTube itself. Tab hands the keyboard to YouTube's
 //      own controls (Tab/Shift+Tab past them comes back). A mouse click into the video while controls are on hands the
 //      keyboard straight back to the page, so W, F and Esc keep working.
 //      o = {player:()=>YT.Player|null, box:()=>Element|null, frame:()=>HTMLIFrameElement|null,
 //           keys:{w:{label:'Watch in Theater',run:p=>…}}, onReturn:()=>…}
 let PM=null;
 const KB=k=>'<kbd>'+k+'</kbd>';
 yc.playerMode=o=>{
  const st={on:false,yt:false};
  const P=()=>o.player&&o.player(),box=()=>o.box&&o.box(),frame=()=>o.frame&&o.frame(),extra=o.keys||{};
  const items=()=>[[KB('Space')+' '+KB('K'),'play / pause'],[KB('←')+KB('→'),'5 s'],[KB('J')+KB('L'),'10 s'],[KB('↑')+KB('↓'),'volume'],[KB('M'),'mute'],[KB('0')+'–'+KB('9'),'jump'],[KB('&lt;')+KB('&gt;'),'speed'],[KB('F'),'fullscreen'],
   ...Object.keys(extra).map(k=>[KB(k.toUpperCase()),extra[k].label]),[KB('Tab'),'Exit YouTube Video Controls'],[KB('Esc'),'done']];
  const card=()=>st.on?'<b>Video Controls ON</b><div class=hk>'+items().map(x=>'<span>'+x[0]+' '+x[1]+'</span>').join('')+'</div>'
   :st.yt?'<b>YouTube’s own controls have the keyboard</b><div>Tab or Shift+Tab past them, or click outside the video, to come back. '+KB('F')+' in there is YouTube’s fullscreen.</div>':null;
  // the "F Video Controls" label under the stage reads "Tab Exit YouTube Video Controls" while the controls are on
  function mark(){document.querySelectorAll('.pmode').forEach(x=>x.classList.remove('pmode'));const b=box();if(st.on&&b)b.classList.add('pmode');
   document.querySelectorAll('.pwret.fkey').forEach(l=>{const mine=st.on&&b&&l===b.nextElementSibling;l.classList.toggle('on',mine);l.classList.remove('flash');l.innerHTML=mine?KB('Tab')+' Exit YouTube Video Controls':KB('F')+' Video Controls'})}
  function set(on){st.on=!!on;if(on)st.yt=false;mark();yc.hint(st.on||st.yt?card:null)}
  st.set=set;
  st.toYouTube=()=>{const fr=frame();if(!fr)return;st.on=false;st.yt=true;mark();yc.hint(card);fr.focus()};
  st.back=()=>{if(!st.yt)return;st.yt=false;yc.hint(null);o.onReturn&&o.onReturn()};
  // the iframe got focus: with controls on that was a mouse click, so the keyboard goes back to the page at once;
  // otherwise (Tab into it, or a click with controls off) YouTube's keys apply and the hint says so
  st.frameFocused=fr=>{if(st.on){try{fr.blur()}catch(e){}try{window.focus()}catch(e){}return}if(!st.yt){st.yt=true;yc.hint(card)}};
  st.pageFocused=()=>{if(st.yt){const a=document.activeElement;if(!a||a.tagName!='IFRAME')st.back()}};
  window.exitPlayerMode=()=>{if(st.on||st.yt){st.yt=false;set(false)}};window.__pmOn=()=>st.on;   // also when the player goes away
  const flash=t=>yc.toast(t,1600);
  const fs=()=>{try{if(document.fullscreenElement){document.exitFullscreen()}else{const fr=frame();if(fr&&fr.requestFullscreen){const r=fr.requestFullscreen();r&&r.catch&&r.catch(()=>{})}}}catch(e){}};
  addEventListener('keydown',e=>{
   if(e.ctrlKey||e.metaKey||e.altKey)return;
   const p=P(),k=e.key,kl=k.toLowerCase(),a=document.activeElement;
   if(!st.on){
    if(kl=='f'&&!yc.typing(a)&&p&&p.getCurrentTime&&box()){e.preventDefault();e.stopImmediatePropagation();set(true)}
    return}
   if(yc.typing(a))return;
   if(!p||!p.getCurrentTime||!box()){set(false);return}
   const eat=()=>{e.preventDefault();e.stopImmediatePropagation()};
   const seek=d=>{p.seekTo(Math.max(0,p.getCurrentTime()+d),true)};
   const vol=d=>{const v=Math.max(0,Math.min(100,(p.getVolume?p.getVolume():100)+d));p.setVolume(v);if(v>0&&p.isMuted&&p.isMuted())p.unMute();flash('Volume '+v+'%')};
   if(k=='Escape'){eat();set(false)}
   else if(kl=='f'||k=='Enter'){eat();fs()}
   else if(extra[kl]&&!e.shiftKey){eat();const x=extra[kl];set(false);x.run(p)}
   else if(k==' '||kl=='k'){eat();p.getPlayerState()==1?p.pauseVideo():p.playVideo()}
   else if(k=='ArrowLeft'){eat();seek(-5)}
   else if(k=='ArrowRight'){eat();seek(5)}
   else if(kl=='j'){eat();seek(-10)}
   else if(kl=='l'){eat();seek(10)}
   else if(k=='ArrowUp'){eat();vol(5)}
   else if(k=='ArrowDown'){eat();vol(-5)}
   else if(kl=='m'){eat();if(p.isMuted&&p.isMuted()){p.unMute();flash('Sound on')}else{p.mute();flash('Muted')}}
   else if(/^[0-9]$/.test(k)){eat();const d=p.getDuration?p.getDuration():0;if(d)p.seekTo(d*(+k)/10,true)}
   else if(k=='<'||k=='>'){eat();const r=(p.getAvailablePlaybackRates?p.getAvailablePlaybackRates():[0.25,0.5,0.75,1,1.25,1.5,1.75,2]),c=p.getPlaybackRate(),i=r.findIndex(x=>x>=c-1e-6);const n=r[Math.max(0,Math.min(r.length-1,(i<0?r.length-1:i)+(k=='>'?1:-1)))];p.setPlaybackRate(n);flash('Speed '+n+'×')}
   else if(k=='Tab'){eat();st.toYouTube()}
   else if(k=='Home'){eat();p.seekTo(0,true)}
   else if(k=='End'){eat();const d=p.getDuration?p.getDuration():0;if(d)p.seekTo(Math.max(0,d-1),true)}
   else if(!['Shift','Control','Alt','Meta','CapsLock'].includes(k)){eat();flash('Video controls are on: Esc finishes them, then the page keys work again')}
  },true);
  PM=st;return st};

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
