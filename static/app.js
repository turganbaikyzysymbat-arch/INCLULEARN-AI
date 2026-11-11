let currentFont=16;
function toggleAccess(){document.getElementById('accessPanel')?.classList.toggle('open')}
function fontStep(step){
  currentFont=Math.max(12,Math.min(28,currentFont+step*2));
  document.querySelectorAll('.adapted-content, .material-tab-panel').forEach(el=>el.style.setProperty('font-size',currentFont+'px','important'));
}
let currentLineHeight = 1.9;

function readingSpacing(step){
    currentLineHeight = Math.max(1.3, Math.min(2.8, currentLineHeight + step * 0.15));
    document.querySelectorAll('.adapted-content, .material-tab-panel').forEach(el => {
        el.style.setProperty('line-height', currentLineHeight, 'important');
    });
}
function toggleReadingContrast(){
  document.querySelectorAll('.adapted-content, .material-tab-panel').forEach(el=>el.classList.toggle('reading-contrast'));
}
function readElement(id){if(!('speechSynthesis'in window)){alert('Бұл браузерде дауыстап оқу қолжетімсіз.');return}speechSynthesis.cancel();const el=document.getElementById(id);if(!el)return;const u=new SpeechSynthesisUtterance(el.innerText);u.lang='kk-KZ';u.rate=.88;speechSynthesis.speak(u)}
function readPage(){const main=document.querySelector('main');if(main)readText(main.innerText)}
function readText(text){if(!('speechSynthesis'in window)){alert('Дауыстап оқу қолжетімсіз');return}speechSynthesis.cancel();let u=new SpeechSynthesisUtterance(text);u.lang='kk-KZ';u.rate=.9;speechSynthesis.speak(u)}
function stopRead(){if('speechSynthesis'in window)speechSynthesis.cancel()}
document.addEventListener('keydown',e=>{if(e.key==='Escape')document.getElementById('accessPanel')?.classList.remove('open')});
document.querySelectorAll('.upload-zone input').forEach(input=>input.addEventListener('change',()=>{if(input.files.length){const label=input.closest('.upload-zone').querySelector('b');if(label)label.textContent=input.files[0].name}}));

// Playful interface micro-interactions: reveal cards as they enter the viewport.
document.addEventListener('DOMContentLoaded',()=>{
  const items=document.querySelectorAll('.quick-card,.material-card,.surface-card,.need-option-creative,.landing-features article');
  if(!('IntersectionObserver' in window)){items.forEach(el=>el.classList.add('is-visible'));return}
  const observer=new IntersectionObserver(entries=>{
    entries.forEach(entry=>{
      if(entry.isIntersecting){entry.target.classList.add('is-visible');observer.unobserve(entry.target)}
    });
  },{threshold:.08});
  items.forEach((el,index)=>{el.classList.add('reveal-item');el.style.setProperty('--reveal-delay',Math.min(index%4,3)*65+'ms');observer.observe(el)});
});
