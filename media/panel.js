/**
 * 号池仪表盘交互 v6.0.0
 * 外部脚本 + cspSource CSP (继承v5.11修复)
 */
try{var V=acquireVsCodeApi();}catch(e){}
var _rmTimer={};
function _esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function S(t,d){V.postMessage(Object.assign({type:t},d||{}));}

// ── 折叠区块 ──
function _toggle(boxId,arrId){
  var box=document.getElementById(boxId),arr=document.getElementById(arrId);
  if(!box)return;
  var op=box.classList.toggle('open');
  if(arr)arr.style.transform=op?'rotate(90deg)':'';
}

// ── 事件委托 ──
document.addEventListener('click',function(e){
  var el=e.target;
  while(el&&el!==document.body){if(el.getAttribute&&el.getAttribute('data-action'))break;el=el.parentElement;}
  if(!el||!el.getAttribute)return;
  var act=el.getAttribute('data-action'),idx=el.getAttribute('data-index');
  if(idx!==null)idx=parseInt(idx);
  switch(act){
    case 'login': S('login',{index:idx}); break;
    case 'copyPwd':
      var cpb=document.getElementById('cp'+idx);
      if(cpb){cpb.textContent='\u2026';cpb.style.opacity='1';}
      S('copyPwd',{index:idx}); break;
    case 'remove':
      var btn=document.getElementById('bx'+idx);
      if(!btn)break;
      if(btn.dataset.confirm==='1'){
        clearTimeout(_rmTimer[idx]);delete _rmTimer[idx];
        var row=document.getElementById('row'+idx);
        if(row){row.style.opacity='0';row.style.transition='opacity .15s';}
        setTimeout(function(){S('remove',{index:idx});},150);
      } else {
        btn.dataset.confirm='1';btn.textContent='确?';btn.style.color='var(--yw)';btn.style.opacity='1';
        _rmTimer[idx]=setTimeout(function(){if(btn){btn.textContent='✕';btn.style.color='';btn.dataset.confirm='0';}},2000);
      }
      break;
    case 'refreshAllAndRotate': S('refreshAllAndRotate'); break;
    case 'smartRotate': S('smartRotate'); break;
    case 'panicSwitch': S('panicSwitch'); break;
    case 'exportAccounts': S('exportAccounts'); break;
    case 'importAccounts': S('importAccounts'); break;
    case 'removeEmpty': S('removeEmpty'); break;
    case 'resetFingerprint': S('resetFingerprint'); break;
    case 'doBatch':
      var t=(document.getElementById('bi')||{}).value;
      if(t&&t.trim()){S('batchAdd',{text:t.trim()});document.getElementById('bi').value='';document.getElementById('preview').innerHTML='';document.getElementById('bi').style.height='28px';}
      break;
    case 'toggleDetail': _toggle('detBox','detArr'); S('toggleDetail'); break;
  }
});

// ── 输入事件 ──
document.addEventListener('input',function(e){
  if(e.target.id==='bi'){
    var t=e.target.value.trim(),p=document.getElementById('preview');
    if(!t){p.innerHTML='';return;}
    S('preview',{text:t});
  }
});

// ── 消息处理 ──
window.addEventListener('message',function(e){
  var m=e.data;
  if(m.type==='toast'){var d=document.createElement('div');d.className='toast '+(m.isError?'terr':'tok');d.textContent=m.msg;document.body.appendChild(d);setTimeout(function(){d.remove()},3000);}
  if(m.type==='loading'){var l=document.getElementById('list');if(l)l.classList.toggle('loading',m.on);}
  if(m.type==='previewResult'){
    var p=document.getElementById('preview');
    if(m.accounts&&m.accounts.length>0){
      p.innerHTML='<span class="pf">'+m.accounts.length+'个</span> '+m.accounts.map(function(a){return '<span class="pe">'+_esc(a.email.split("@")[0])+'</span>:<span class="pp">'+_esc(a.password.substring(0,4))+'..</span>'}).join(' ');
    } else {
      p.innerHTML='<span style="color:var(--rd);font-size:9px">未识别</span>';
    }
  }
  if(m.type==='pwdResult'){
    var btn=document.getElementById('cp'+m.index);
    if(btn&&m.pwd){
      navigator.clipboard.writeText(m.pwd).then(function(){
        btn.textContent='✓';btn.style.color='var(--gn)';
        setTimeout(function(){btn.textContent='📋';btn.style.color='';btn.style.opacity='';},1500);
      }).catch(function(){btn.textContent='!';setTimeout(function(){btn.textContent='📋';},1000);});
    }
  }
});
