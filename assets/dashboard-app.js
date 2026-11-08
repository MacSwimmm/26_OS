    const $ = (s, root=document) => root.querySelector(s);
    const $$ = (s, root=document) => [...root.querySelectorAll(s)];
    const DEFAULT_CONFIG={title:"茶歇服务调度控制台",project:"茶歇服务员任务调度",subtitle:"逐步观察任务调度、资源竞争与中断恢复",accent:"#32f08c",footerText:"TeaFlow",widgets:{timeline:true,tasks:true,features:true,chart:true,resources:true,events:true},customCards:[]};
    const widgetNames={timeline:"执行时间线",tasks:"任务队列",features:"核心机制",chart:"系统运行趋势",resources:"资源占用",events:"事件日志"};
    const featureList=[
      ["01","动态调度","优先级、截止时间与到达顺序共同决定任务队列。"],
      ["02","资源互斥","茶歇台、取杯区、回收区与通道 逐项分配。"],
      ["03","银行家算法","资源分配前执行安全序列检查，避免不安全状态。"],
      ["04","死锁恢复","等待图检测环，并按回滚策略恢复可恢复任务。"],
      ["05","中断响应","紧急任务可抢占；环境与故障事件支持暂停恢复。"],
      ["06","指标评估","完成率、响应时长、冲突、回滚与资源利用率。"]
    ];
    const eventNames={arrival:"任务到达",resume:"任务恢复",dependency_wait:"前置依赖等待",request_submitted:"普通任务到达",duplicate_cup_ignored:"重复杯子事件已忽略",static_order:"静态调度顺序",start:"任务开始",stage_start:"阶段开始",stage_complete:"阶段完成",complete:"任务完成",resource_wait:"资源等待",urgent_submitted:"紧急任务到达",preempt:"发生抢占",pause:"任务暂停",resume_ready:"恢复就绪",deadlock_detected:"检测到死锁",rollback:"回滚恢复",deadlock_unresolved:"死锁未解除",resource_blocked:"资源关闭",resource_restored:"资源恢复",interrupt:"中断事件",cancel:"任务撤销",stop:"仿真结束"};
    const eventColors={complete:"var(--green)",start:"var(--accent)",stage_start:"var(--accent)",urgent_submitted:"var(--red)",preempt:"var(--red)",pause:"var(--blue)",resume_ready:"var(--blue)",deadlock_detected:"var(--red)",rollback:"var(--amber)",resource_wait:"var(--amber)",resource_blocked:"var(--amber)",resource_restored:"var(--green)"};
    const resourceNames={tea_table:"茶歇台",cup_station:"取杯区",return_station:"回收区",corridor:"通行通道",request_board:"请求公告板"};
    const stateNames={pending:"未到达",ready:"就绪",running:"运行中",blocked:"等待条件",paused:"暂停",completed:"已完成",cancelled:"已撤销"};
    let config=loadConfig(), data=null, experimentData=null, activeView="overview", currentTime=0, timer=null, speed=900, taskFilter="all", runBusy=false, playbackState="ready";
    function validateConfig(value){if(!value||typeof value!=="object"||Array.isArray(value))throw new Error("设置必须为对象");for(const k of ["title","project","subtitle","footerText"])if(value[k]!=null&&typeof value[k]!=="string")throw new Error("文字设置需为字符串");if(value.accent&&!/^#[\da-f]{6}$/i.test(value.accent))throw new Error("强调色格式错误");if(value.customCards!=null&&(!Array.isArray(value.customCards)||value.customCards.length>4||value.customCards.some(c=>!c||typeof c.label!=="string"||typeof c.value!=="string")))throw new Error("自定义指标格式错误");if(value.widgets!=null&&(typeof value.widgets!=="object"||Array.isArray(value.widgets)||Object.values(value.widgets).some(v=>typeof v!=="boolean")))throw new Error("模块设置需为布尔值");return value}
    function loadConfig(base=DEFAULT_CONFIG){try{const saved=validateConfig(JSON.parse(localStorage.getItem("teaflow-config")||"{}"));return {...base,...saved,widgets:{...base.widgets,...saved.widgets}}}catch{return structuredClone(base)}}
    function esc(v){return String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
    function toast(text){const el=$("#toast");el.textContent=text;el.classList.add("show");setTimeout(()=>el.classList.remove("show"),2200)}
    function current(){return data?.snapshots?.[Math.max(0,Math.min(currentTime,(data?.snapshots?.length||1)-1))]||null}
    function applyConfig(){document.documentElement.style.setProperty("--accent",config.accent||DEFAULT_CONFIG.accent);document.documentElement.style.setProperty("--accent-soft",`${config.accent||DEFAULT_CONFIG.accent}1a`);$("#pageTitle").textContent=config.title;$("#sessionTitle").textContent=config.project;$("#railProject").textContent=config.project;$("#pageSubtitle").textContent=config.subtitle;$("#footerProject").textContent=config.project;$("#footerWordmarkText").textContent=typeof config.footerText==="string"&&config.footerText.trim()?config.footerText.trim().slice(0,40):DEFAULT_CONFIG.footerText;for(const [key] of Object.entries(widgetNames)){const node=$(`[data-widget="${key}"]`);if(node)node.hidden=config.widgets[key]===false}renderCustomCards();document.dispatchEvent(new Event("teaflow:config"))}
    function renderCustomCards(){const host=$("#metrics");$$(".custom-metric",host).forEach(n=>n.remove());(config.customCards||[]).slice(0,4).forEach((card,i)=>{const el=document.createElement("article");el.className="metric custom-metric";el.style.setProperty("--metric-color",i%2?"var(--blue)":"var(--green)");el.innerHTML=`<div class="metric-label"><span>${esc(card.label||"自定义指标")}</span><i class="metric-dot"></i></div><div class="metric-value" style="font-size:22px">${esc(card.value||"—")}</div><div class="metric-foot">${esc(card.note||"自定义内容")}</div>`;host.append(el)})}
    function setView(name){const changed=activeView!==name;activeView=name;$$(".view").forEach(el=>el.classList.toggle("active",el.dataset.page===name));$$(".nav button[data-view]").forEach(el=>el.classList.toggle("active",el.dataset.view===name));if(name==="experiments")loadExperiment();if(changed)window.scrollTo({top:0,behavior:"instant"})}
    function statusPill(state){return `<span class="pill ${esc(state)}">${stateNames[state]||esc(state)}</span>`}
    function metricCard(label,value,note,color,wash){return `<article class="metric" style="--metric-color:${color};--metric-wash:${wash}"><div class="metric-label"><span>${label}</span><i class="metric-dot"></i></div><div class="metric-value">${value}</div><div class="metric-foot">${note}</div></article>`}
    function renderMetrics(snap){const m=snap?.metrics||{};const tasks=Object.values(snap?.tasks||{}),done=tasks.filter(t=>t.state==="completed"),running=tasks.filter(t=>t.state==="running").length;const response=done.length?Math.round(done.reduce((sum,t)=>sum+(t.finished_at-(t.arrival_time||0)),0)/done.length*100)/100:null;const cards=[metricCard("任务完成率",`${Math.round((m.completion_rate||0)*100)}%`,`${m.completed_tasks??done.length} / ${m.total_tasks??tasks.length} 项完成`,"var(--green)","#edf7ef"),metricCard("正在执行",String(running),`${tasks.filter(t=>t.state==="blocked").length} 项等待资源`,"var(--accent)","#fff0ec"),metricCard("平均响应时间",response==null?"—":`${response}<small style="font-size:12px;font-weight:500"> t</small>`,"按当前已完成任务计算","var(--blue)","#eef2fd"),metricCard("资源冲突",String(m.conflict_count??0),`死锁 ${m.deadlock_count??0} 次 · 抢占 ${m.preemptions??0} 次`,"var(--amber)","#fff6e9")];$("#metrics").innerHTML=cards.join("");renderCustomCards()}
    function renderTaskRows(snap,full=false){const host=full?$("#taskTable"):$("#taskPreview");if(!host)return;const tasks=Object.values(snap?.tasks||{});if(!tasks.length){host.innerHTML='<div class="empty">运行仿真后显示任务状态</div>';return}if(full){const filtered=taskFilter==="all"?tasks:tasks.filter(t=>t.state===taskFilter);$("#taskTableNote").textContent=`${tasks.length} 项任务 · 模拟时刻 t = ${snap.time}`;host.innerHTML=filtered.map(t=>{const pct=t.duration?Math.max(0,Math.min(100,((t.completed_work||0)/t.duration)*100)):0;const held=Object.keys(t.held_resources||{}).map(k=>resourceNames[k]||k).join("、")||"—";return `<tr><td><strong>${esc(t.task_id)}　${esc(t.name)}</strong><div class="panel-sub">${t.urgent?"紧急任务 · ":""}到达 t=${t.submitted_at}</div></td><td>${statusPill(t.state)}</td><td>${t.priority}</td><td>t = ${t.deadline}</td><td>${esc(t.stage_name||t.name)}<div class="panel-sub">${esc(t.waiting_reason||"")}</div></td><td><div class="progress" style="width:100px"><span style="width:${pct}%"></span></div></td><td>${esc(held)}</td></tr>`}).join("")||'<tr><td colspan="7" class="empty">没有符合筛选条件的任务</td></tr>';return}host.innerHTML='<div class="task-row table-head"><span>任务名称</span><span>进度</span><span>状态</span><span>优先级</span></div>'+tasks.slice(0,5).map(t=>{const pct=t.duration?Math.max(0,Math.min(100,((t.completed_work||0)/t.duration)*100)):0;return `<div class="task-row"><div class="task-main"><span class="task-code">${esc(t.task_id)}</span><span class="task-name"><strong>${esc(t.name)}</strong><small>${t.urgent?"紧急 · ":""}${esc(t.stage_name||"")}</small></span></div><div><div class="progress"><span style="width:${pct}%"></span></div><div class="progress-note">${t.state==="completed"?"已完成":`剩余 ${Math.max(0,t.duration-(t.completed_work||0))} t`}</div></div>${statusPill(t.state)}<span class="priority">P${t.priority}</span></div>`}).join("")+`<div class="task-more"><button class="text-btn" data-goto="tasks">查看全部 ${tasks.length} 项任务　→</button></div>`}
    function renderResources(snap,full=false){const entries=Object.entries(snap?.resources||{}).filter(([,r])=>!r.shared);if(full){$("#resourceMetrics").innerHTML=entries.map(([name,r])=>metricCard(resourceNames[name]||name,`${Object.values(r.holders||{}).reduce((a,b)=>a+b,0)}/${r.capacity}`,`可用 ${r.available} 个资源位`,"var(--blue)","#eef2fd")).join("");$("#resourceTable").innerHTML=entries.map(([name,r])=>{const pct=Math.round((Object.values(r.holders||{}).reduce((a,b)=>a+b,0))/r.capacity*100),holders=Object.entries(r.holders).map(([id,n])=>`${id} ×${n}`).join("、")||"无";return `<tr><td><strong>${resourceNames[name]||esc(name)}</strong></td><td>${r.capacity}</td><td>${r.available}</td><td>${pct}%</td><td>${esc(holders)}</td><td>${r.blocked_until>snap.time?'<span class="pill blocked">临时不可用</span>':(Object.keys(r.holders).length?'<span class="pill running">使用中</span>':'<span class="pill completed">可分配</span>')}</td></tr>`}).join("");return}$("#resourcePreview").innerHTML=entries.map(([name,r],i)=>{const used=Object.values(r.holders||{}).reduce((a,b)=>a+b,0),pct=Math.round(used/r.capacity*100),holder=Object.keys(r.holders).join(", ")||(r.blocked_until>snap.time?"临时不可用":"当前空闲");return `<div class="resource-item"><div class="resource-name"><span class="resource-icon">${["A","B","C","D"][i]||"R"}</span>${resourceNames[name]||esc(name)}</div><span class="resource-value">${used} / ${r.capacity} 已占用</span><div class="resource-track"><span style="width:${pct}%;--bar:${["var(--accent)","var(--blue)","var(--green)","var(--amber)"][i%4]}"></span></div><div class="resource-meta"><span>${esc(holder)}</span><span>${pct}%</span></div></div>`}).join("")||'<div class="empty">运行仿真后显示资源分配</div>'}
    function renderEvents(events,host,limit=12,upto=Infinity){const list=(events||[]).filter(e=>e.time<=upto).slice(-limit).reverse();$(host).innerHTML=list.length?list.map((e,i)=>{const label=eventNames[e.event]||e.event,task=(e.experiment?`[${e.experiment}] `:"")+(e.task_id?`任务 ${e.task_id}`:""),detail=e.reason||e.description||e.resource||e.stage||e.completed_stage||(e.order?e.order.join(" → "):"");return `<div class="event-row ${i===0?"is-new":""}"><span class="event-time">t ${String(e.time).padStart(2,"0")}</span><i class="event-pin" style="--event-color:${eventColors[e.event]||"var(--blue)"}"></i><div><div class="event-title">${esc(label)}${task?` · ${esc(task)}`:""}</div><div class="event-detail">${esc(detail)}</div></div></div>`}).join(""):'<div class="empty">当前时刻没有调度事件</div>'}
    function renderChart(){const host=$("#chart");const snaps=data?.snapshots||[];if(!snaps.length){host.innerHTML='<div class="empty">仿真趋势将在运行后生成</div>';return}const n=snaps.length,completed=snaps.map(s=>Object.values(s.tasks).filter(t=>t.state==="completed").length),active=snaps.map(s=>Object.values(s.tasks).filter(t=>["running","blocked","paused"].includes(t.state)).length),max=Math.max(1,...completed,...active),w=520,h=150,p=14;function path(values){return values.map((v,i)=>`${i?"L":"M"}${p+i*(w-2*p)/Math.max(1,n-1)} ${h-p-(v/max)*(h-2*p)}`).join(" ")}const x=p+currentTime*(w-2*p)/Math.max(1,n-1);host.innerHTML=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="任务状态趋势"><defs><linearGradient id="chartFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="var(--accent)" stop-opacity=".18"/><stop offset="1" stop-color="var(--accent)" stop-opacity="0"/></linearGradient></defs><line class="chart-grid" x1="${p}" y1="${p}" x2="${w-p}" y2="${p}"/><line class="chart-grid" x1="${p}" y1="${h/2}" x2="${w-p}" y2="${h/2}"/><line class="chart-grid" x1="${p}" y1="${h-p}" x2="${w-p}" y2="${h-p}"/><path class="chart-fill" d="${path(completed)} L${w-p} ${h-p} L${p} ${h-p}Z"/><path class="chart-line" d="${path(completed)}"/><path d="${path(active)}" fill="none" stroke="var(--green)" stroke-width="2" stroke-linecap="round"/><line x1="${x}" y1="${p}" x2="${x}" y2="${h-p}" stroke="#333a35" stroke-width="1" stroke-dasharray="3 4"/>${completed.map((v,i)=>i===currentTime?`<circle class="chart-node" cx="${x}" cy="${h-p-(v/max)*(h-2*p)}" r="4"/>`:"").join("")}<text class="chart-tick" x="2" y="${p+3}">${max}</text><text class="chart-tick" x="3" y="${h-p}">0</text></svg>`}
    function renderGantt(host,snapshots){
      if(!data?.result||!snapshots?.length){host.innerHTML='<div class="empty">运行仿真后显示任务区间</div>';return}
      const tasks=Object.values(data.result.tasks||{});
      const max=Math.max(1,snapshots.at(-1).time,...tasks.map(task=>task.finished_at||0));
      const now=current()?.time??0;
      host.innerHTML=tasks.map((task,index)=>{
        // A boundary snapshot at t records execution over [t,t+1).
        const intervals=[];
        for(const snapshot of snapshots){
          const ran=snapshot.tasks[task.task_id]?.state==="running"&&snapshot.time<snapshots.at(-1).time;
          if(!ran)continue;
          const start=snapshot.time,end=start+1,last=intervals.at(-1);
          if(last&&last.end===start)last.end=end;else intervals.push({start,end});
        }
        const bars=intervals.flatMap(({start,end})=>{
          const base=`<i class="gantt-bar future" style="left:${start/max*100}%;width:${(end-start)/max*100}%" title="${esc(task.task_id)} · t=${start}–${end}"></i>`;
          const played=Math.min(end,now)-start;
          return [base,played>0?`<i class="gantt-bar ${task.urgent?"urgent":""}" style="left:${start/max*100}%;width:${played/max*100}%;--bar-color:${["var(--accent)","var(--blue)","var(--green)","var(--amber)"][index%4]}"></i>`:""];
        }).join("");
        return `<div class="gantt-row"><span class="gantt-name">${esc(task.task_id)} · ${esc(task.name)}</span><div class="gantt-track">${bars}<i class="gantt-now" style="left:${Math.min(100,now/max*100)}%"></i></div></div>`;
      }).join("")+`<div class="gantt-scale"><span></span><div class="scale-line"><span>t = 0</span><span>${Math.round(max*.25)}</span><span>${Math.round(max*.5)}</span><span>${Math.round(max*.75)}</span><span>t = ${max}</span></div></div>`;
    }
    function renderOverview(){const snap=current();if(!snap)return;$("#dateChip").textContent=`离散时钟 · t = ${snap.time}`;$("#timeLabel").textContent=`t = ${snap.time}`;$("#timeRange").max=Math.max(0,(data.snapshots?.length||1)-1);$("#timeRange").value=currentTime;renderMetrics(snap);renderTaskRows(snap);renderTaskRows(snap,true);renderResources(snap);renderResources(snap,true);renderEvents(data.result?.trace||[],"#eventFeed",12,snap.time);$("#eventCount").textContent=`${(data.result?.trace||[]).filter(e=>e.time<=snap.time).length} 条事件`;renderChart();renderGantt($("#gantt"),data.snapshots);renderGantt($("#ganttFull"),data.snapshots);$("#taskTableNote").textContent=`${Object.keys(snap.tasks).length} 项任务 · 模拟时刻 t = ${snap.time}`;$("#featureGrid").innerHTML=featureList.map(x=>`<article class="feature"><i class="feature-mark">${x[0]}</i><strong>${x[1]}</strong><span>${x[2]}</span></article>`).join("");if(activeView==="experiments")loadExperiment()}
    function setPlaybackState(state){
      playbackState=state;
      const labels={ready:"等待开始",loading:"正在计算",playing:"运行中",paused:"已暂停",completed:"仿真已结束",error:"运行失败"};
      $("#playState").textContent=labels[state]||state;
      $("#simulation").dataset.playback=state;
      $("#playButton").textContent=state==="playing"?"Ⅱ 暂停":state==="completed"?"↻ 重播":"▶ 播放";
      $("#heroEngineState").textContent=state==="playing"?"仿真运行中":state==="completed"?"本次仿真已结束":state==="loading"?"正在计算调度":state==="error"?"连接异常，请重试":"本地离散仿真";
    }
    async function runScenario(name,silent=false){
      if(runBusy)return false;
      runBusy=true;
      pause("loading");
      $("#runError").hidden=true;
      $("#toast").classList.remove("show");
      const controls=$$("#runButton, #heroRun, #sessionRun, #scenario, #experimentMode, #playButton, #stepBack, #stepForward, #timeRange, .scenario-choice");
      controls.forEach(button=>button.disabled=true);
      $("#runButton .run-text").textContent="正在计算";
      try{
        const response=await fetch("/api/run",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({scenario:name})});
        const result=await response.json();
        if(!response.ok)throw new Error(result.error||"仿真请求失败");
        $("#connectionState").textContent="本地引擎已连接";
        if(result.comparisons){
          experimentData=result;
          $("#experimentMode").value=name;
          setView("experiments");
          setPlaybackState(data?"paused":"ready");
        }else{
          if(!result.snapshots?.length)throw new Error("引擎未返回可播放的仿真数据");
          data=result;currentTime=0;
          $("#sessionScenario").textContent=result.label;
          renderOverview();setPlaybackState("ready");
          if(!silent){
            if(activeView==="experiments")setView("overview");
            startPlayback();
            if(activeView==="overview"){
              document.dispatchEvent(new CustomEvent("teaflow:show-widget",{detail:"timeline"}));
              $("#sessionControls").scrollIntoView({behavior:matchMedia("(prefers-reduced-motion: reduce)").matches?"instant":"smooth",block:"start"});
            }
          }
        }
        return true;
      }catch(error){
        setPlaybackState("error");
        $("#runErrorMessage").textContent=`仿真未能启动：${error.message}。请确认本地服务仍在运行后重试。`;
        $("#runError").hidden=false;$("#runError").scrollIntoView({block:"center",behavior:"instant"});
        $("#connectionState").textContent="本次请求失败";
        return false;
      }finally{
        runBusy=false;
        controls.forEach(button=>button.disabled=false);
        $("#runButton .run-text").textContent="开始仿真";
      }
    }
    function pause(state){
      if(timer){clearInterval(timer);timer=null}
      setPlaybackState(state||(data&&currentTime>=data.snapshots.length-1?"completed":data?"paused":"ready"));
    }
    function startPlayback(){
      if(!data?.snapshots?.length)return;
      if(timer)clearInterval(timer);
      if(currentTime>=data.snapshots.length-1)currentTime=0;
      renderOverview();setPlaybackState("playing");
      timer=setInterval(()=>{
        currentTime=Math.min(currentTime+1,data.snapshots.length-1);
        renderOverview();
        if(currentTime>=data.snapshots.length-1)pause("completed");
      },speed);
    }
    function play(){if(runBusy)return;if(!data?.snapshots?.length)return;timer?pause():startPlayback()}
    function comparisonView(){if(!experimentData?.comparisons){$("#experimentContent").innerHTML='<div class="panel"><div class="empty">选择“调度策略对比”或“死锁三策略”，再运行仿真查看数据。</div></div>';return}const rows=experimentData.comparisons, deadlock=experimentData.scenario==="deadlock";$("#experimentContent").innerHTML=`<div class="metrics">${metricCard("实验方案",String(rows.length),deadlock?"银行家避免 / 检测 / 恢复":"基线与调度开关对比","var(--blue)","#eef2fd")}${metricCard("完成任务",rows.map(x=>x.completed_tasks).join(" / "),"按方案顺序排列","var(--green)","#edf7ef")}${metricCard("死锁次数",rows.map(x=>x.deadlock_count).join(" / "),"检测结果来自等待图环检测","var(--red)","#fff0ec")}${metricCard("回滚工作量",rows.map(x=>x.rollback_work).join(" / "),"恢复带来的重做工作","var(--amber)","#fff6e9")}</div><div class="comparison">${rows.map(r=>`<article class="compare-tile"><h3>${esc(r.label||r.name)}</h3><div class="compare-row"><span>完成率</span><strong class="good">${Math.round((r.completion_rate||0)*100)}%</strong></div><div class="compare-row"><span>完成任务</span><strong>${r.completed_tasks} / ${r.total_tasks}</strong></div><div class="compare-row"><span>平均响应时间</span><strong>${r.average_response_time==null?"—":`${r.average_response_time} t`}</strong></div><div class="compare-row"><span>紧急任务错失率</span><strong>${r.urgent_task_miss_rate==null?"—":`${Math.round(r.urgent_task_miss_rate*100)}%`}</strong></div><div class="compare-row"><span>抢占次数</span><strong>${r.preemptions}</strong></div><div class="compare-row"><span>资源冲突</span><strong>${r.conflict_count}</strong></div><div class="compare-row"><span>安全拒绝</span><strong>${r.safety_rejection_count}</strong></div><div class="compare-row"><span>死锁 / 回滚</span><strong>${r.deadlock_count} / ${r.rollback_count}</strong></div></article>`).join("")}</div>`;const traces=experimentData.results?Object.entries(experimentData.results).flatMap(([name,r])=>(r.trace||[]).map(e=>({...e,experiment:experimentData.comparisons.find(c=>c.name===name)?.label||name}))).sort((a,b)=>a.time-b.time):[];renderEvents(traces,"#experimentEvents",18)}
    function loadExperiment(){if(!$("#experimentContent"))return;if(experimentData?.comparisons){$("#experimentMode").value=experimentData.scenario;comparisonView()}else comparisonView()}
    let settingsReturnFocus;
    function openDrawer(){settingsReturnFocus=document.activeElement;syncForm();$("#drawer").inert=false;$("#scrim").classList.add("open");$("#drawer").classList.add("open");$("main").inert=true;$("#closeSettings").focus()}

    function closeDrawer(){$("#scrim").classList.remove("open");$("#drawer").classList.remove("open");$("#drawer").inert=true;$("main").inert=false;settingsReturnFocus?.focus({preventScroll:true})}
    document.addEventListener("keydown",event=>{
      if(!$("#drawer").classList.contains("open"))return;
      if(event.key==="Escape"){event.preventDefault();closeDrawer()}
      if(event.key==="Tab"){
        const controls=$$("button,input,select,textarea",$("#drawer")).filter(el=>!el.disabled&&el.offsetParent!==null);
        const first=controls[0],last=controls.at(-1);
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus()}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus()}
      }
    });
    function syncForm(){$("#customTitle").value=config.title;$("#customProject").value=config.project;$("#customFooterText").value=config.footerText||DEFAULT_CONFIG.footerText;$("#customAccent").value=config.accent;$("#accentText").value=config.accent;$("#customSubtitle").value=config.subtitle;$("#customCards").value=JSON.stringify(config.customCards||[],null,2);$("#widgetSwitches").innerHTML=Object.entries(widgetNames).map(([key,label])=>`<div class="switch-row">${label}<button class="switch" role="switch" aria-checked="${config.widgets[key]!==false}" data-widget-switch="${key}" aria-label="显示${label}"></button></div>`).join("")}
    function saveForm(){let cards;try{cards=JSON.parse($("#customCards").value||"[]");if(!Array.isArray(cards)||cards.length>4||cards.some(c=>!c||typeof c.label!=="string"||typeof c.value!=="string"))throw new Error("请填写最多 4 个包含 label 和 value 的指标对象")}catch(e){toast(`自定义指标 JSON 格式无效：${e.message}`);return}const color=$("#accentText").value.trim();if(!/^#[\da-f]{6}$/i.test(color)){toast("强调色需为 6 位 HEX 颜色值");return}const widgets={...config.widgets};$$('[data-widget-switch]').forEach(sw=>widgets[sw.dataset.widgetSwitch]=sw.getAttribute("aria-checked")==="true");config={...config,title:$("#customTitle").value.trim()||DEFAULT_CONFIG.title,project:$("#customProject").value.trim()||DEFAULT_CONFIG.project,footerText:$("#customFooterText").value.trim()||DEFAULT_CONFIG.footerText,accent:color,subtitle:$("#customSubtitle").value.trim()||DEFAULT_CONFIG.subtitle,widgets,customCards:cards.slice(0,4)};localStorage.setItem("teaflow-config",JSON.stringify(config));applyConfig();closeDrawer();toast("控制台设置已保存")}
    function download(name,object){const blob=new Blob([JSON.stringify(object,null,2)],{type:"application/json"}),url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;a.click();URL.revokeObjectURL(url)}
    function eventByTime(step){if(!data?.snapshots?.length)return;currentTime=Math.max(0,Math.min(data.snapshots.length-1,currentTime+step));renderOverview();pause()}
    $$(".nav button[data-view]").forEach(b=>b.addEventListener("click",()=>setView(b.dataset.view)));
    $(".site-brand").addEventListener("click",()=>setView("overview"));
    document.addEventListener("click",e=>{const goto=e.target.closest("[data-goto]");if(goto)setView(goto.dataset.goto)});
    $("#runButton").addEventListener("click",()=>runScenario($("#scenario").value));
    $("#heroRun").addEventListener("click",()=>runScenario($("#scenario").value));
    $("#sessionRun").addEventListener("click",()=>runScenario($("#scenario").value));
    $("#retryRun").addEventListener("click",()=>runScenario($("#scenario").value));
    $("#playButton").addEventListener("click",play);$("#stepBack").addEventListener("click",()=>{pause();eventByTime(-1)});$("#stepForward").addEventListener("click",()=>{pause();eventByTime(1)});$("#timeRange").addEventListener("input",e=>{pause();currentTime=Number(e.target.value);renderOverview();pause()});$("#speed").addEventListener("change",e=>{speed=Number(e.target.value);if(timer){pause();play()}});$("#taskFilter").addEventListener("change",e=>{taskFilter=e.target.value;const snap=current();if(snap)renderTaskRows(snap,true)});
    $("#experimentMode").addEventListener("change",e=>{$("#scenario").value=e.target.value;runScenario(e.target.value)});$("#noticeAction").addEventListener("click",()=>setView("experiments"));$("#noticeActionInner").addEventListener("click",()=>setView("experiments"));$("#tasksExport").addEventListener("click",()=>data?.result?download("teaflow-simulation.json",data.result):toast("请先运行单场景仿真"));
    $("#openSettings").addEventListener("click",openDrawer);$("#closeSettings").addEventListener("click",closeDrawer);$("#scrim").addEventListener("click",closeDrawer);$("#saveConfig").addEventListener("click",saveForm);$("#resetConfig").addEventListener("click",()=>{config=structuredClone(DEFAULT_CONFIG);localStorage.removeItem("teaflow-config");applyConfig();syncForm();toast("已恢复默认设置")});$("#customAccent").addEventListener("input",e=>$("#accentText").value=e.target.value);$("#accentText").addEventListener("input",e=>{if(/^#[\da-f]{6}$/i.test(e.target.value))$("#customAccent").value=e.target.value});
    $("#widgetSwitches").addEventListener("click",e=>{const sw=e.target.closest("[data-widget-switch]");if(sw)sw.setAttribute("aria-checked",sw.getAttribute("aria-checked")==="true"?"false":"true")});$("#exportConfig").addEventListener("click",()=>download("teaflow-dashboard-config.json",config));$("#importConfig").addEventListener("click",()=>$("#configFile").click());$("#configFile").addEventListener("change",async e=>{try{const imported=validateConfig(JSON.parse(await e.target.files[0].text()));config={...DEFAULT_CONFIG,...imported,widgets:{...DEFAULT_CONFIG.widgets,...imported.widgets}};syncForm();toast("配置已载入，点击保存后生效")}catch{toast("配置文件无法读取")}e.target.value=""});
    $("#scenario").addEventListener("change",e=>{if(e.target.value==="compare"||e.target.value==="deadlock"){$("#experimentMode").value=e.target.value}});
    async function boot(){try{const remote=await fetch("/api/config").then(response=>response.ok?response.json():{});config=loadConfig({...DEFAULT_CONFIG,...remote,widgets:{...DEFAULT_CONFIG.widgets,...(remote.widgets||{})}})}catch{}applyConfig();syncForm();$("#featureGrid").innerHTML=featureList.map(x=>`<article class="feature"><i class="feature-mark">${x[0]}</i><strong>${x[1]}</strong><span>${x[2]}</span></article>`).join("");$("#experimentContent").innerHTML='<div class="panel"><div class="empty">选择策略并运行仿真，查看真实调度结果。</div></div>';$("#eventFeed").innerHTML='<div class="empty">等待运行数据</div>';$("#taskPreview").innerHTML='<div class="empty">运行仿真后显示任务状态</div>';$("#resourcePreview").innerHTML='<div class="empty">运行仿真后显示资源分配</div>';$("#chart").innerHTML='<div class="empty">仿真趋势将在运行后生成</div>';$("#gantt").innerHTML='<div class="empty">运行仿真后显示任务区间</div>';runScenario("baseline",true)}boot();
