// YouCommander — shared page behaviour: the keyboard help overlay (press ? on any page).
(function(){
 const h=document.getElementById('help');if(!h)return;
 const typing=el=>el&&(el.tagName=='TEXTAREA'||el.tagName=='SELECT'||(el.tagName=='INPUT'&&el.type!='checkbox'));
 const open=o=>h.classList.toggle('open',o);
 window.toggleHelp=()=>open(!h.classList.contains('open'));
 addEventListener('keydown',e=>{
  if(h.classList.contains('open')){
   if(e.key=='Escape'||e.key=='?'){e.preventDefault();e.stopImmediatePropagation();open(false)}
   else if(!typing(document.activeElement)&&!e.ctrlKey&&!e.metaKey){e.preventDefault();e.stopImmediatePropagation()}
   return}
  if(e.key=='?'&&!typing(document.activeElement)&&!e.ctrlKey&&!e.metaKey&&!e.altKey){e.preventDefault();e.stopImmediatePropagation();open(true)}
 },true);
 h.addEventListener('click',e=>{if(e.target===h)open(false)});
 document.querySelectorAll('[data-help]').forEach(b=>b.addEventListener('click',()=>{open(true);b.blur()}));
})();
