const API = '';
    let selectedAlias = null;
    let detailHours = 1;
    let charts = {};
    let refreshTimer = 30;
    let countdownInterval;

    const $ = id => document.getElementById(id);
    const fmt = (n, d=2) => n==null?'—':(+n).toFixed(d);
    const fmtN = (n, d=2) => {
      if(n==null) return '—';
      const v=+n; return (v>=0?'+':'')+v.toFixed(d);
    };

    // Parse timestamp to Date, treating no-tz strings as UTC+7
    function parseToBangkok(s) {
      if(!s) return null;
      try {
        const hasTz = s.includes('Z')||/[+-]\d{2}:?\d{2}$/.test(s);
        if(hasTz) return new Date(s);
        return new Date(s.replace(' ','T')+'+07:00');
      } catch(e) { return null; }
    }

    function fmtDate(s) {
      if(!s) return '—';
      const d = parseToBangkok(s);
      if(!d||isNaN(d.getTime())) return s;
      return new Intl.DateTimeFormat('sv-SE', {
        timeZone:'Asia/Bangkok',
        year:'numeric',month:'2-digit',day:'2-digit',
        hour:'2-digit',minute:'2-digit',second:'2-digit'
      }).format(d);
    }

    function toChartLabel(s, showDate=false) {
      const d = parseToBangkok(s);
      if(!d||isNaN(d.getTime())) return '';
      const opts = showDate
        ? {timeZone:'Asia/Bangkok',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}
        : {timeZone:'Asia/Bangkok',hour:'2-digit',minute:'2-digit'};
      return new Intl.DateTimeFormat('sv-SE', opts).format(d);
    }

    // Convert Date to Bangkok ISO string (no tz suffix) for API query
    function toBangkokISO(d) {
      const p = new Intl.DateTimeFormat('sv-SE', {
        timeZone:'Asia/Bangkok',
        year:'numeric',month:'2-digit',day:'2-digit',
        hour:'2-digit',minute:'2-digit',second:'2-digit'
      }).format(d).split(' ');
      return p[0]+'T'+p[1];
    }

    function toBangkokLocalInput(d) {
      const p = new Intl.DateTimeFormat('sv-SE', {
        timeZone:'Asia/Bangkok',
        year:'numeric',month:'2-digit',day:'2-digit',
        hour:'2-digit',minute:'2-digit'
      }).format(d).split(' ');
      return p[0]+'T'+p[1];
    }

    function showToast(msg, color='var(--green)') {
      const t=$('toast'); t.textContent=msg; t.style.borderColor=color;
      t.classList.add('show'); setTimeout(()=>t.classList.remove('show'),3000);
    }

    function ddColor(pct) {
      if(pct<5) return 'var(--green)';
      if(pct<15) return 'var(--yellow)';
      return 'var(--red)';
    }

    function getStatus(ts) {
      if(!ts) return 'offline';
      const d = parseToBangkok(ts);
      if(!d) return 'offline';
      const diff = (Date.now()-d.getTime())/1000;
      if(diff<120) return 'online';
      if(diff<300) return 'stale';
      return 'offline';
    }

    // Clock
    setInterval(()=>{
      $('clock').textContent = new Intl.DateTimeFormat('sv-SE',{
        timeZone:'Asia/Bangkok',hour:'2-digit',minute:'2-digit',second:'2-digit'
      }).format(new Date())+' (UTC+7)';
    },1000);

    // Auto refresh
    function startCountdown() {
      clearInterval(countdownInterval);
      refreshTimer=30;
      countdownInterval=setInterval(()=>{
        refreshTimer--;
        $('countdown').textContent=refreshTimer+'s';
        if(refreshTimer<=0){
          refreshTimer=30;
          loadOverview();
          if(selectedAlias) refreshDetail();
        }
      },1000);
    }
    startCountdown();

    window.onTabLoaded = function(name) {
      if(name==='overview') loadOverview();
      if(name==='settings') loadSettings();
      if(name==='detail'||name==='history') populateAccountSelects();
      if(name==='alerts') loadAlertsTab();
    };

    function switchTab(name, btn) {
      document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));
      document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
      const t = $('tab-'+name);
      if(t) t.classList.add('active');
      if(btn) btn.classList.add('active');
      if(window.onTabLoaded) window.onTabLoaded(name);
    }

    async function loadOverview() {
      const grid=$('accounts-grid');
      if(!grid) return; // Not on overview tab
      const showHidden = $('chk-show-hidden')&&$('chk-show-hidden').checked;
      let allAccounts=[], atData=[];
      try {
        const [res,atRes]=await Promise.all([fetch(API+'/api/latest'),fetch(API+'/api/alltime')]);
        allAccounts=await res.json();
        if(atRes.ok) atData=await atRes.json();
      } catch(e) {
        try{const res=await fetch(API+'/api/latest');allAccounts=await res.json();}catch(e2){}
      }
      const accounts = showHidden?allAccounts:allAccounts.filter(a=>a.active!==0);

      const activeAliases=new Set(accounts.map(a=>a.alias));
      const activeAtData=atData.filter(d=>activeAliases.has(d.alias));

      if(activeAtData.length && $('alltime-banner') && $('alltime-grid')){
        $('alltime-banner').style.display='block';
        const maxDD=activeAtData.reduce((a,b)=>b.max_drawdown_pct>a.max_drawdown_pct?b:a,activeAtData[0]);
        const maxPr=activeAtData.reduce((a,b)=>b.max_profit>a.max_profit?b:a,activeAtData[0]);
        const minPr=activeAtData.reduce((a,b)=>b.min_profit<a.min_profit?b:a,activeAtData[0]);
        const withML=activeAtData.filter(a=>a.min_margin_level!=null&&a.min_margin_level>0);
        const minML=withML.length?withML.reduce((a,b)=>b.min_margin_level<a.min_margin_level?b:a,withML[0]):activeAtData[0];
        $('alltime-grid').innerHTML=`
      <div class="alltime-item"><div class="al-label">📉 Drawdown มากที่สุด</div><div class="al-account">${maxDD.alias}</div><div class="al-val" style="color:var(--red)">${fmt(maxDD.max_drawdown_pct)}%</div></div>
      <div class="alltime-item"><div class="al-label">📈 กำไรมากที่สุด</div><div class="al-account">${maxPr.alias}</div><div class="al-val" style="color:var(--green)">+${fmt(maxPr.max_profit)}</div></div>
      <div class="alltime-item"><div class="al-label">📉 ขาดทุนมากที่สุด</div><div class="al-account">${minPr.alias}</div><div class="al-val" style="color:var(--red)">${fmt(minPr.min_profit)}</div></div>
      <div class="alltime-item"><div class="al-label">⚠️ Margin Level ต่ำสุด</div><div class="al-account">${minML.alias}</div><div class="al-val" style="color:var(--yellow)">${fmt(minML.min_margin_level)}%</div></div>
    `;
      } else if($('alltime-banner')) {
        $('alltime-banner').style.display='none';
      }

      if(!accounts.length){
        grid.innerHTML=`<div class="empty"><h2>ยังไม่มี Account</h2><p>รอข้อมูลจาก MT5 EA...</p></div>`;
        return;
      }

      grid.innerHTML='';
      accounts.sort((a,b)=>(a.display_name||a.alias).localeCompare(b.display_name||b.alias));

      accounts.forEach(acc=>{
        const dd=acc.drawdown_pct||0;
        const eDD=acc.equity_dd_pct||0;
        const ddColor_=ddColor(dd);
        const eDDColor_=ddColor(eDD);
        const profitClass=acc.profit>=0?'positive':'negative';
        const status=getStatus(acc.received_at);
        const card=document.createElement('div');
        card.className='account-card'+(selectedAlias===acc.alias?' selected':'');
        card.onclick=()=>selectAccount(acc.alias,card);
        card.innerHTML=`
      <div class="card-header">
        <div>
          <div class="account-name">${acc.display_name||acc.alias}</div>
          <div class="account-num">${acc.alias} · #${acc.account_number} · ${acc.broker||'—'} · 1:${acc.leverage}</div>
        </div>
        <div class="status-dot ${status}"></div>
      </div>
      <div class="metrics-grid">
        <div class="metric"><div class="metric-label">Balance</div><div class="metric-value">${fmt(acc.balance)} <span style="font-size:10px;color:var(--muted)">${acc.currency||'USD'}</span></div></div>
        <div class="metric"><div class="metric-label">Equity</div><div class="metric-value">${fmt(acc.equity)}</div></div>
        
        <div class="metric"><div class="metric-label">Profit Today</div><div class="metric-value ${acc.realized_today>=0?'positive':'negative'}">${fmtN(acc.realized_today)}</div></div>
        <div class="metric"><div class="metric-label">Profit This Week</div><div class="metric-value ${acc.realized_week>=0?'positive':'negative'}">${fmtN(acc.realized_week)}</div></div>
        
        <div class="metric"><div class="metric-label">Profit All-Time</div><div class="metric-value ${acc.realized_all>=0?'positive':'negative'}">${fmtN(acc.realized_all)}</div></div>
        <div class="metric"><div class="metric-label">Floating Profit</div><div class="metric-value ${profitClass}">${fmtN(acc.profit)}</div></div>
        
        <div class="metric"><div class="metric-label">Margin Level</div><div class="metric-value ${acc.margin_level>200?'positive':acc.margin_level>100?'warn':'negative'}">${fmt(acc.margin_level)}%</div></div>
        <div class="metric"><div class="metric-label">Free Margin</div><div class="metric-value">${fmt(acc.free_margin)}</div></div>
        
        <div class="metric" style="grid-column: 1 / -1;"><div class="metric-label">Open Orders</div><div class="metric-value">${acc.open_orders||0} <span style="font-size:10px;color:var(--muted)">(${fmt(acc.total_lots,2)} lots)</span> <span style="font-size:10px;color:var(--green)">▲Buy:${acc.buy_orders||0}</span> <span style="font-size:10px;color:var(--red)">▼Sell:${acc.sell_orders||0}</span></div></div>
      </div>
      <div class="dd-bar-wrap">
        <div class="dd-bar-label"><span>Bal DD <span style="font-size:9px;color:var(--muted)">(from peak)</span></span><span style="color:${ddColor_}">${fmt(dd,2)}%</span></div>
        <div class="dd-bar-bg"><div class="dd-bar-fill" style="width:${Math.min(dd,100)}%;background:${ddColor_}"></div></div>
        <div class="dd-bar-label" style="margin-top:6px"><span>Eq DD <span style="font-size:9px;color:var(--muted)">(floating)</span></span><span style="color:${eDDColor_}">${fmt(eDD,2)}%</span></div>
        <div class="dd-bar-bg"><div class="dd-bar-fill" style="width:${Math.min(eDD,100)}%;background:${eDDColor_}"></div></div>
      </div>
      <div class="card-footer">อัพเดท: ${fmtDate(acc.received_at)}</div>
      <div class="card-actions">
        <button class="icon-btn" onclick="event.stopPropagation();showRenameModal('${acc.alias}','${(acc.display_name||acc.alias).replace(/'/g,"&#39;")}')">✏️ ตั้งชื่อ</button>
        <button class="icon-btn warn" onclick="event.stopPropagation();toggleAccount('${acc.alias}')">${acc.active!==0?'🙈 ซ่อน':'👁 แสดง'}</button>
      </div>
    `;
        if(acc.active===0) card.classList.add('hidden-acc');
        grid.appendChild(card);
      });
    }

    function selectAccount(alias, card) {
      selectedAlias=alias;
      document.querySelectorAll('.account-card').forEach(c=>c.classList.remove('selected'));
      if(card) card.classList.add('selected');
      $('detail-panel').style.display='block';
      refreshDetail();
    }

    async function refreshDetail() {
      if(!selectedAlias) return;
      $('dp-title').innerHTML=selectedAlias+' <span class="spinner"></span>';

      let hist, stats={}, at={};

      if(detailHours===0){
        // ALL-TIME
        try {
          const [hRes,sRes,aRes]=await Promise.all([
            fetch(`${API}/api/history_all/${selectedAlias}?limit=2000&field=balance,equity,drawdown_pct,profit,open_orders,total_lots,ts`),
            fetch(`${API}/api/stats/${selectedAlias}?days=3650`),
            fetch(`${API}/api/alltime/${selectedAlias}`)
          ]);
          hist=await hRes.json();
          if(sRes.ok) stats=await sRes.json();
          if(aRes.ok) at=await aRes.json();
        } catch(e){ $('dp-title').textContent=selectedAlias; return; }
      } else {
        const hrs=detailHours;
        const endNow=new Date();
        const startNow=new Date(endNow-hrs*3600000);
        const startISO=toBangkokISO(startNow);
        const endISO=toBangkokISO(endNow);
        try {
          const [hRes,sRes,aRes]=await Promise.all([
            fetch(`${API}/api/history/${selectedAlias}?start=${startISO}&end=${endISO}&limit=2000&field=balance,equity,drawdown_pct,profit,open_orders,total_lots,ts`),
            fetch(`${API}/api/stats/${selectedAlias}?days=${Math.max(1,Math.ceil(hrs/24))}`),
            fetch(`${API}/api/alltime/${selectedAlias}`)
          ]);
          hist=await hRes.json();
          if(sRes.ok) stats=await sRes.json();
          if(aRes.ok) at=await aRes.json();
        } catch(e){ $('dp-title').textContent=selectedAlias; return; }
      }

      $('dp-title').textContent=selectedAlias+(detailHours===0?' (ALL TIME)':'');

      const strip=$('stats-strip');
      const sb=(l,v,c)=>`<div class="stat-box"><div class="label">${l}</div><div class="val"${c?' style="color:'+c+'"':''}>${v}</div></div>`;
      const sbAt=(l,v,c)=>`<div class="stat-box" style="border:1px solid #1e4a6e"><div class="label" style="color:var(--accent)">&#127942; ${l}</div><div class="val"${c?' style="color:'+c+'"':''}>${v}</div></div>`;
      strip.innerHTML=
        sb('Avg Balance',fmt(stats.avg_balance))+
        sb('Max Balance',fmt(stats.max_balance),'var(--green)')+
        sb('Min Balance',fmt(stats.min_balance),'var(--red)')+
        sb('Max Equity',fmt(stats.max_equity),'var(--green)')+
        sb('Min Equity',fmt(stats.min_equity),'var(--red)')+
        sb('Max Profit',fmtN(stats.max_profit),'var(--green)')+
        sb('Min Profit',fmtN(stats.min_profit),'var(--red)')+
        sb('Max Drawdown',fmt(stats.max_drawdown_pct)+'%',ddColor(stats.max_drawdown_pct))+
        sb('Avg Drawdown',fmt(stats.avg_drawdown_pct)+'%')+
        sb('Max Orders',stats.max_open_orders||0)+
        sb('Avg Margin Lv',fmt(stats.avg_margin_level)+'%')+
        sb('Snapshots',hist.count||0)+
        sbAt('All-Time Max DD',fmt(at.max_drawdown_pct)+'%','var(--red)')+
        sbAt('All-Time Max Profit',fmtN(at.max_profit),'var(--green)')+
        sbAt('All-Time Min Profit',fmtN(at.min_profit),'var(--red)')+
        sbAt('All-Time Max Balance',fmt(at.max_balance),'var(--green)')+
        sbAt('All-Time Min Balance',fmt(at.min_balance),'var(--red)');

      const data=hist.data||[];
      const showDate=detailHours===0||detailHours>=24;
      const labels=data.map(d=>toChartLabel(d.ts,showDate));

      const chartDefaults={
        responsive:true, maintainAspectRatio:true, animation:false,
        plugins:{legend:{labels:{color:'#64748b',font:{size:11}}}},
        scales:{
          x:{ticks:{color:'#64748b',maxTicksLimit:8,font:{size:10}},grid:{color:'#1e2d52'}},
          y:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'#1e2d52'}}
        }
      };

      const makeChart=(id,cfg)=>{
        if(charts[id]) charts[id].destroy();
        charts[id]=new Chart($(id).getContext('2d'),cfg);
      };

      makeChart('chart-be',{type:'line',data:{labels,datasets:[
        {label:'Balance',data:data.map(d=>d.balance),borderColor:'#00d4ff',backgroundColor:'rgba(0,212,255,.05)',borderWidth:1.5,pointRadius:0,tension:.3},
        {label:'Equity',data:data.map(d=>d.equity),borderColor:'#7c3aed',backgroundColor:'rgba(124,58,237,.05)',borderWidth:1.5,pointRadius:0,tension:.3}
      ]},options:chartDefaults});

      makeChart('chart-dd',{type:'line',data:{labels,datasets:[
        {label:'DD%',data:data.map(d=>d.drawdown_pct),borderColor:'#ff4444',backgroundColor:'rgba(255,68,68,.1)',borderWidth:1.5,pointRadius:0,fill:true,tension:.3}
      ]},options:chartDefaults});

      makeChart('chart-pl',{type:'bar',data:{labels,datasets:[{
        label:'Profit',data:data.map(d=>d.profit),
        backgroundColor:data.map(d=>d.profit>=0?'rgba(0,230,118,.6)':'rgba(255,68,68,.6)'),borderRadius:2
      }]},options:{...chartDefaults,animation:false}});

      makeChart('chart-orders',{type:'line',data:{labels,datasets:[
        {label:'Orders',data:data.map(d=>d.open_orders),borderColor:'#ffd600',borderWidth:1.5,pointRadius:0,tension:.3,yAxisID:'y'},
        {label:'Lots',data:data.map(d=>d.total_lots),borderColor:'#ff7043',borderWidth:1.5,pointRadius:0,tension:.3,yAxisID:'y1'}
      ]},options:{...chartDefaults,scales:{
        x:{...chartDefaults.scales.x},
        y:{...chartDefaults.scales.y,position:'left'},
        y1:{...chartDefaults.scales.y,position:'right',grid:{display:false}}
      }}});
    }

    function setRange(hours,label,btn) {
      detailHours=hours;
      document.querySelectorAll('.range-btn').forEach(b=>b.classList.remove('active'));
      if(btn) btn.classList.add('active');
      if(selectedAlias) refreshDetail();
    }

    async function loadHistoryTable() {
      const alias=$('hist-account-sel').value;
      if(!alias){showToast('กรุณาเลือก Account','var(--yellow)');return;}
      let start=$('hist-start').value||toBangkokLocalInput(new Date(Date.now()-86400000));
      let end=$('hist-end').value||toBangkokLocalInput(new Date());
      const limit=$('hist-limit').value;
      if(start&&start.length===16) start+=':00';
      if(end&&end.length===16) end+=':59';
      const wrap=$('history-table-wrap');
      wrap.innerHTML='<div style="text-align:center;padding:30px;color:var(--muted)">กำลังโหลด...</div>';
      const res=await fetch(`${API}/api/history/${alias}?start=${start}&end=${end}&limit=${limit}&field=balance,equity,profit,drawdown_pct,equity_dd_pct,margin_level,open_orders,total_lots,buy_lots,sell_lots,ts`);
      const hist=await res.json();
      const data=(hist.data||[]).reverse();
      if(!data.length){wrap.innerHTML='<div class="empty"><p>ไม่มีข้อมูลในช่วงเวลานี้</p></div>';return;}
      wrap.innerHTML=`
    <div style="font-size:12px;color:var(--muted);margin-bottom:8px">${data.length} รายการ</div>
    <div class="data-table-wrap">
    <table>
      <thead><tr>
        <th>เวลา (UTC+7)</th><th>Balance</th><th>Equity</th><th>Profit</th>
        <th>DD%</th><th>Eq DD%</th><th>Margin Lv</th><th>Orders</th><th>Lots (Buy/Sell)</th>
      </tr></thead>
      <tbody>
        ${data.map(r=>`<tr>
          <td>${fmtDate(r.ts)}</td>
          <td>${fmt(r.balance)}</td>
          <td>${fmt(r.equity)}</td>
          <td style="color:${r.profit>=0?'var(--green)':'var(--red)'}">${fmtN(r.profit)}</td>
          <td style="color:${ddColor(r.drawdown_pct)}">${fmt(r.drawdown_pct,2)}%</td>
          <td>${fmt(r.equity_dd_pct,2)}%</td>
          <td style="color:${r.margin_level>200?'var(--green)':r.margin_level>100?'var(--yellow)':'var(--red)'}">${fmt(r.margin_level,1)}%</td>
          <td>${r.open_orders}</td>
          <td>${fmt(r.total_lots,2)} <span style="font-size:10px;color:var(--muted)">(${fmt(r.buy_lots||0,2)}/${fmt(r.sell_lots||0,2)})</span></td>
        </tr>`).join('')}
      </tbody>
    </table>
    </div>
  `;
    }

    async function loadDetailTab() {
      const alias=$('detail-account-sel').value;
      if(!alias) return;
      let start=$('detail-start').value;
      let end=$('detail-end').value;
      if(start&&start.length===16) start+=':00';
      if(end&&end.length===16) end+=':59';
      const res=await fetch(`${API}/api/history/${alias}?start=${start}&end=${end}&limit=2000&field=balance,equity,drawdown_pct,equity_dd_pct,profit,open_orders,buy_orders,sell_orders,total_lots,buy_lots,sell_lots,margin_level,free_margin,ts`);
      const hist=await res.json();
      const data=hist.data||[];
      const wrap=$('detail-tab-content');
      if(!data.length){wrap.innerHTML='<div class="empty"><p>ไม่มีข้อมูลในช่วงเวลานี้</p></div>';return;}

      const startDt=parseToBangkok(data[0].ts);
      const endDt=parseToBangkok(data[data.length-1].ts);
      const spanHours=startDt&&endDt?(endDt-startDt)/3600000:0;
      const showDate=spanHours>=24;

      wrap.innerHTML=`
    <div style="color:var(--muted);font-size:12px;margin-bottom:16px">${alias} · ${data.length} snapshot · <span style="color:var(--accent)">${fmtDate(data[0].ts)}</span> → <span style="color:var(--accent)">${fmtDate(data[data.length-1].ts)}</span></div>
    <div class="chart-grid" id="detail-charts">
      <div class="chart-box"><h3>Balance / Equity</h3><canvas id="d-chart-be"></canvas></div>
      <div class="chart-box"><h3>Drawdown % / Equity DD%</h3><canvas id="d-chart-dd"></canvas></div>
      <div class="chart-box"><h3>Profit / Loss</h3><canvas id="d-chart-pl"></canvas></div>
      <div class="chart-box"><h3>Margin Level %</h3><canvas id="d-chart-ml"></canvas></div>
      <div class="chart-box"><h3>Open Orders — Buy / Sell</h3><canvas id="d-chart-ord"></canvas></div>
      <div class="chart-box"><h3>Total Lots</h3><canvas id="d-chart-lots"></canvas></div>
      <div class="chart-box"><h3>Free Margin</h3><canvas id="d-chart-fm"></canvas></div>
    </div>
  `;
      const labels=data.map(d=>toChartLabel(d.ts,showDate));
      const co={
        responsive:true,maintainAspectRatio:true,animation:false,
        plugins:{legend:{labels:{color:'#64748b',font:{size:11}}}},
        scales:{
          x:{ticks:{color:'#64748b',maxTicksLimit:8,font:{size:10}},grid:{color:'#1e2d52'}},
          y:{ticks:{color:'#64748b',font:{size:10}},grid:{color:'#1e2d52'}}
        }
      };
      const mk=(id,cfg)=>{if(charts['d'+id])charts['d'+id].destroy();charts['d'+id]=new Chart($(id).getContext('2d'),cfg);};

      mk('d-chart-be',{type:'line',data:{labels,datasets:[
        {label:'Balance',data:data.map(d=>d.balance),borderColor:'#00d4ff',borderWidth:1.5,pointRadius:0,tension:.3},
        {label:'Equity',data:data.map(d=>d.equity),borderColor:'#7c3aed',borderWidth:1.5,pointRadius:0,tension:.3}
      ]},options:co});
      mk('d-chart-dd',{type:'line',data:{labels,datasets:[
        {label:'DD%',data:data.map(d=>d.drawdown_pct),borderColor:'#ff4444',backgroundColor:'rgba(255,68,68,.08)',fill:true,borderWidth:1.5,pointRadius:0,tension:.3},
        {label:'Equity DD%',data:data.map(d=>d.equity_dd_pct),borderColor:'#ff8a65',borderWidth:1.5,pointRadius:0,tension:.3}
      ]},options:co});
      mk('d-chart-pl',{type:'bar',data:{labels,datasets:[
        {label:'Profit',data:data.map(d=>d.profit),backgroundColor:data.map(d=>d.profit>=0?'rgba(0,230,118,.6)':'rgba(255,68,68,.6)'),borderRadius:2}
      ]},options:co});
      mk('d-chart-ml',{type:'line',data:{labels,datasets:[
        {label:'Margin Level%',data:data.map(d=>d.margin_level),borderColor:'#ffd600',borderWidth:1.5,pointRadius:0,tension:.3}
      ]},options:co});
      mk('d-chart-ord',{type:'bar',data:{labels,datasets:[
        {label:'Buy Orders',data:data.map(d=>d.buy_orders||0),backgroundColor:'rgba(0,230,118,.6)',borderRadius:2},
        {label:'Sell Orders',data:data.map(d=>d.sell_orders||0),backgroundColor:'rgba(255,68,68,.6)',borderRadius:2}
      ]},options:co});
      mk('d-chart-lots',{type:'line',data:{labels,datasets:[
        {label:'Total Lots',data:data.map(d=>d.total_lots),borderColor:'#ff7043',backgroundColor:'rgba(255,112,67,.08)',fill:true,borderWidth:1.5,pointRadius:0,tension:.3},
        {label:'Buy Lots',data:data.map(d=>d.buy_lots||0),borderColor:'#00e676',borderWidth:1.5,pointRadius:0,tension:.3,borderDash:[5,5]},
        {label:'Sell Lots',data:data.map(d=>d.sell_lots||0),borderColor:'#ff4444',borderWidth:1.5,pointRadius:0,tension:.3,borderDash:[5,5]}
      ]},options:co});
      mk('d-chart-fm',{type:'line',data:{labels,datasets:[
        {label:'Free Margin',data:data.map(d=>d.free_margin),borderColor:'#26c6da',borderWidth:1.5,pointRadius:0,tension:.3}
      ]},options:co});
    }

    async function loadSettings() {
      const res=await fetch(API+'/api/accounts');
      const accounts=await res.json();
      const wrap=$('settings-content');
      if(!accounts.length){wrap.innerHTML='<div class="empty"><p>ยังไม่มี Account ที่ส่งข้อมูลมา</p></div>';return;}
      wrap.innerHTML=accounts.map(acc=>`
    <div class="settings-card">
      <h3>⚙️ <span>${acc.display_name||acc.alias}</span>
        <span style="font-size:10px;color:var(--muted);font-weight:400">${acc.display_name?'('+acc.alias+')':''}</span>
        <span style="margin-left:auto;font-size:11px;padding:2px 8px;border-radius:4px;background:${acc.active?'rgba(0,230,118,.15)':'rgba(100,116,139,.15)'};color:${acc.active?'var(--green)':'var(--muted)'}">${acc.active?'● Active':'● Hidden'}</span>
      </h3>
      <div class="form-row"><label>ชื่อที่แสดง</label>
        <div style="display:flex;gap:8px">
          <input type="text" id="dn-${acc.alias}" value="${acc.display_name||''}" placeholder="${acc.alias}" style="flex:1">
          <button class="btn" style="white-space:nowrap" onclick="saveDisplayName('${acc.alias}')">✏️ บันทึกชื่อ</button>
        </div>
      </div>
      <div class="form-row"><label>Account Number</label>
        <input type="text" value="${acc.account_number||''}" disabled style="opacity:.5">
      </div>
      <div class="form-row"><label>Broker / Server</label>
        <input type="text" value="${acc.broker||''} / ${acc.server||''}" disabled style="opacity:.5">
      </div>
      <div class="form-row"><label>ทุนเริ่มต้น</label>
        <input type="number" id="ib-${acc.alias}" value="${acc.initial_balance||10000}" min="0" step="100">
      </div>
      <div class="form-row"><label>หมายเหตุ</label>
        <input type="text" id="note-${acc.alias}" value="${acc.note||''}">
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn" onclick="saveSettings('${acc.alias}')" style="flex:1">💾 บันทึก</button>
        <button class="btn" onclick="toggleAccount('${acc.alias}')" style="background:var(--bg3);border:1px solid var(--border);color:var(--text);flex:1">${acc.active?'🙈 ซ่อน':'👁 แสดง'}</button>
        <button class="btn danger" onclick="deleteAccount('${acc.alias}')" style="flex:1">🗑 ลบ</button>
      </div>
    </div>
  `).join('');
    }

    async function saveDisplayName(alias) {
      const name=$('dn-'+alias).value.trim();
      await fetch(`${API}/api/accounts/${alias}/rename`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:name})});
      showToast('✓ บันทึกชื่อแล้ว');
      loadSettings();
    }

    async function saveSettings(alias) {
      const ib=parseFloat($('ib-'+alias).value)||10000;
      const note=$('note-'+alias).value;
      await fetch(`${API}/api/accounts/${alias}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({alias,initial_balance:ib,note})});
      showToast('✓ บันทึกการตั้งค่าแล้ว');
    }

    async function populateAccountSelects() {
      const res=await fetch(API+'/api/accounts');
      const accounts=await res.json();
      const opts=accounts.map(a=>`<option value="${a.alias}">${a.display_name||a.alias}</option>`).join('');
      ['detail-account-sel','hist-account-sel'].forEach(id=>{
        const sel=$(id); const curr=sel.value;
        sel.innerHTML='<option value="">-- เลือก Account --</option>'+opts;
        if(curr) sel.value=curr;
      });
      const now=new Date();
      const yesterday=new Date(now-86400000);
      ['hist-start','detail-start'].forEach(id=>{if($(id)&&!$(id).value)$(id).value=toBangkokLocalInput(yesterday);});
      ['hist-end','detail-end'].forEach(id=>{if($(id)&&!$(id).value)$(id).value=toBangkokLocalInput(now);});
    }

    // === ALERTS TAB ===
    async function loadAlertsTab() {
      try {
        const res=await fetch(API+'/api/alerts/settings');
        const s=await res.json();
        $('tg-global-enabled').checked=!!s.global_enabled;
        $('tg-chatid').value=s.chat_id||'';
        $('tg-status').innerHTML=s.has_token
          ?'<span style="color:var(--green)">✅ Bot Token ตั้งค่าแล้ว</span>'
          :'<span style="color:var(--yellow)">⚠️ ยังไม่ได้ตั้งค่า Bot Token</span>';

        const accs=await (await fetch(API+'/api/latest')).json();
        const accSettings=s.account_settings||{};
        const wrap=$('account-alert-settings');
        const active=accs.filter(a=>a.active!==0);
        if(!active.length){wrap.innerHTML='<div class="empty"><p>ยังไม่มี Account</p></div>';return;}
        wrap.innerHTML=active.map(a=>`
          <div class="toggle-row">
            <div>
              <div class="toggle-label">${a.display_name||a.alias}</div>
              <div class="toggle-sub">${a.alias}</div>
            </div>
            <label class="toggle-switch">
              <input type="checkbox" id="acc-alert-${a.alias}" ${accSettings[a.alias]===false?'':'checked'} onchange="toggleAccountAlert('${a.alias}',this.checked)">
              <span class="toggle-slider"></span>
            </label>
          </div>
        `).join('');
      } catch(e) { console.error('loadAlertsTab error',e); }
    }

    async function saveAlertSettings() {
      const token=$('tg-token').value.trim();
      const chatId=$('tg-chatid').value.trim();
      const enabled=$('tg-global-enabled').checked;
      try {
        const res=await fetch(API+'/api/alerts/settings',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({global_enabled:enabled,bot_token:token,chat_id:chatId})
        });
        if(res.ok){
          showToast('✓ บันทึกการตั้งค่าการแจ้งเตือนแล้ว');
          $('tg-token').value='';
          await loadAlertsTab();
        }
      } catch(e){showToast('❌ เกิดข้อผิดพลาด','var(--red)');}
    }

    async function toggleAccountAlert(alias,enabled) {
      try {
        await fetch(API+'/api/alerts/account',{
          method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({alias,enabled})
        });
        showToast(`✓ ${enabled?'เปิด':'ปิด'}การแจ้งเตือน ${alias}`);
      } catch(e){showToast('❌ เกิดข้อผิดพลาด','var(--red)');}
    }

    async function testTelegram() {
      const token=$('tg-token').value.trim();
      const chatId=$('tg-chatid').value.trim();
      if(token||chatId) await saveAlertSettings();
      try {
        const res=await fetch(API+'/api/alerts/test',{method:'POST'});
        if(res.ok){
          showToast('✅ ส่งข้อความทดสอบสำเร็จ! ตรวจสอบ Telegram');
        } else {
          const err=await res.json();
          showToast('❌ '+(err.detail||'ส่งไม่สำเร็จ'),'var(--red)');
        }
      } catch(e){showToast('❌ เกิดข้อผิดพลาด: '+e.message,'var(--red)');}
    }

    async function loadAlertStatus() {
      try {
        const res=await fetch(API+'/api/alerts/status');
        const data=await res.json();
        const wrap=$('alert-status-list');
        if(!data.length){wrap.innerHTML='<div class="empty"><p>ไม่มีข้อมูลสถานะ (server อาจเพิ่งรีสตาร์ท)</p></div>';return;}
        wrap.innerHTML=data.map(s=>{
          const color=s.is_offline?'var(--red)':'var(--green)';
          const txt=s.is_offline?`ไม่มีข้อมูลมา ${s.elapsed_minutes} นาที`:`ปกติ (${s.elapsed_minutes} นาทีที่แล้ว)`;
          const cntTxt=s.alert_count>0?`แจ้งเตือนแล้ว ${s.alert_count} ครั้ง`:'';
          return `
            <div class="alert-status-item">
              <div class="a-dot" style="background:${color};box-shadow:0 0 6px ${color}"></div>
              <div class="a-name">
                <div>${s.display_name}</div>
                <div style="font-size:10px;color:var(--muted)">${s.alias}</div>
              </div>
              <div style="text-align:right">
                <div style="font-size:11px;font-family:var(--mono);color:${color}">${txt}</div>
                <div style="font-size:11px;font-family:var(--mono);color:var(--yellow)">${cntTxt}</div>
              </div>
            </div>
          `;
        }).join('');
      } catch(e){$('alert-status-list').innerHTML='<div class="empty"><p>ไม่สามารถโหลดสถานะได้</p></div>';}
    }

    let _renameAlias=null;
    function showRenameModal(alias,currentName){
      _renameAlias=alias;
      $('modal-name-input').value=(currentName&&currentName!==alias)?currentName:'';
      $('modal-name-input').placeholder=alias;
      $('modal-overlay').style.display='flex';
      setTimeout(()=>$('modal-name-input').focus(),50);
    }
    function closeModal(){$('modal-overlay').style.display='none';_renameAlias=null;}

    async function doRename(){
      if(!_renameAlias) return;
      const name=$('modal-name-input').value.trim();
      await fetch(`${API}/api/accounts/${_renameAlias}/rename`,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({display_name:name})});
      closeModal();showToast('✓ ตั้งชื่อแล้ว');loadOverview();
    }

    async function toggleAccount(alias){
      await fetch(`${API}/api/accounts/${alias}/toggle`,{method:'PUT'});
      loadOverview();showToast('✓ เปลี่ยนสถานะ Account แล้ว');
    }

    async function deleteAccount(alias){
      if(!confirm('ยืนยันลบ Account "'+alias+'" และข้อมูลทั้งหมด?\nไม่สามารถกู้คืนได้!')) return;
      await fetch(`${API}/api/accounts/${alias}`,{method:'DELETE'});
      if(selectedAlias===alias){selectedAlias=null;$('detail-panel').style.display='none';}
      showToast('✓ ลบ Account แล้ว','var(--red)');
      loadOverview();loadSettings();
    }

    document.addEventListener('keydown',e=>{if(e.key==='Escape')closeModal();});
    loadOverview();