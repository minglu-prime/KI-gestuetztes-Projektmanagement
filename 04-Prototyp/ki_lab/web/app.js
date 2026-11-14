'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const hash = new URLSearchParams(location.hash.slice(1));
let token = hash.get('session') || sessionStorage.getItem('pm-token') || '';
let state = null, health = null, dirty = false, saveTimer, saveChain = Promise.resolve(), tick, poll, deadline = 0, generation = 0;
const error = message => { $('error').textContent = message; $('error').hidden = !message; };
const active = () => state?.rounds.find(r => r.status === 'active');
const backupKey = () => 'pm-draft-' + token + '-' + active()?.case_id + '-' + active()?.stage;
function context() { const r = state?.rounds.find(r=>r.status==='active' || r.status==='ready'); return r ? {case_id:r.case_id,stage:r.stage} : null; }
async function api(path, body, sessionToken=token) {
  if(body && ['start','save','plan','submit','ai'].includes(path)) body={...body,_context:body._context || context()};
  const response = await fetch('/api/' + path, {method: body === undefined ? 'GET' : 'POST',
    headers: {'Content-Type':'application/json', 'Authorization':'Bearer ' + sessionToken},
    ...(body === undefined ? {} : {body:JSON.stringify(body)})});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || 'Anfrage fehlgeschlagen.');
  return value;
}
function download(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function bind(id, action) { $(id)?.addEventListener('click', async event => { event.preventDefault(); error(''); try { await action(); } catch (err) { error(err.message); } }); }
function nav(step) { ['prep','first','second','reflect'].forEach((s,i) => $('nav-' + s).classList.toggle('selected', i === step)); }
function hero() { return `<section class="hero"><div><p class="eyebrow">Mensch · Methode · Maschine</p><h1>Was verändert KI<br>im <em>Projektmanagement?</em></h1><p class="lead">Zwei Arbeitsweisen. Ein nachvollziehbarer Vergleich. Untersuchen Sie, wie KI Zeit, Qualität und menschliche Entscheidungen beeinflusst.</p></div><div class="experiment-art" aria-label="Manuelle Arbeit und KI-Assistenz werden verglichen"><div class="art-top"><span>DAS EXPERIMENT</span><span>01 / 02</span></div><div class="art-flow"><div class="art-node"><strong>Mensch</strong>manuell planen</div><span>↔</span><div class="art-node"><strong>Mensch + KI</strong>prüfen & entscheiden</div></div><div class="art-result">ZEIT &nbsp; / &nbsp; QUALITÄT &nbsp; / &nbsp; VERANTWORTUNG</div></div></section><div class="stats"><div class="stat"><strong>02</strong><span>Arbeitsweisen<br>im Vergleich</span></div><div class="stat"><strong>25 min</strong><span>je Runde<br>für beide Aufgaben</span></div><div class="stat"><strong>~70 min</strong><span>inkl. Einführung<br>und Reflexion</span></div></div>`; }
function practice() { return `<details><summary>Übung öffnen · nicht gewertet</summary><p class="small">${esc(state.practice.text)}</p><label for="practice">Ihr Übungsentwurf</label><textarea id="practice" class="practice-box" placeholder="U1 … / U2 … / Risiko …"></textarea><details><summary>Lösung nach der Übung ansehen</summary><p class="small">${esc(state.practice.solution)}</p></details></details>`; }
function intro() {
  nav(0);
  $('app').innerHTML = hero() + `<div class="grid-two"><section class="card"><p class="card-number">01 — SO FUNKTIONIERT ES</p><h2>Planen. Hinterfragen. Entscheiden.</h2><ol class="steps"><li><span>1</span><p>Vorbereiten & üben<br><small>Regeln lesen und die Oberfläche kennenlernen.</small></p></li><li><span>2</span><p>Zwei Fälle bearbeiten<br><small>Je ein Basisplan und eine Risiko-/Änderungsanalyse.</small></p></li><li><span>3</span><p>Arbeitsweise reflektieren<br><small>Was hat geholfen? Was musste geprüft werden?</small></p></li></ol><div class="note">Es wird die Arbeitsweise untersucht, nicht Ihre persönliche Leistung. Auch Fehler und unvollständige Ergebnisse sind wertvolle Beobachtungen.</div>${state ? practice() : ''}</section><section class="card"><p class="card-number">02 — IHR STUDIENRAUM</p><h2>${state ? 'Bereit für die erste Runde?' : 'Prototyp erkunden'}</h2>${state ? setupForm() : `<p class="muted small">Der offene Einstieg erstellt ausschließlich eine Pilot-Sitzung. Für die formale Studie erhalten Sie einen persönlichen Einladungslink von der Studienleitung.</p><label for="group">Ablauf für diesen Pilot</label><select id="group"><option value="1">1 · Manuell A → KI B</option><option value="2">2 · KI B → Manuell A</option><option value="3">3 · Manuell B → KI A</option><option value="4">4 · KI A → Manuell B</option></select><div class="actions"><button class="primary full-width" id="create">Pilot-Sitzung öffnen →</button></div>`}<p class="note ${health.ai_configured ? '' : 'warning'}">${health.ai_configured ? 'KI-Verbindung konfiguriert. Erfolgreichen Live-Pilot vor der formalen Studie prüfen.' : 'KI noch nicht konfiguriert. Manuelle Bearbeitung ist möglich; KI-Anfragen zeigen einen protokollierten Fehler, keine simulierte Antwort.'}</p></section></div>`;
  bind('create', async () => { const result = await api('pilot', {group:Number($('group').value)}); token = result.token; sessionStorage.setItem('pm-token',token); location.hash = 'session=' + token; await load(); });
  bind('start', async () => {
    state = await api('start', {consent:$('consent').checked, pm_experience:$('pm').value, ai_experience:$('ai').value});
    render();
  });
}
function setupForm() { return `<p class="small muted">Kennung: <strong>${esc(state.participant)}</strong>. Freiwillige Teilnahme. Abbruch ist jederzeit durch Schließen möglich; die Zeit läuft weiter und vorhandene Teilstände bleiben erhalten. Für Löschung wenden Sie sich mit Ihrer Kennung an die Studienleitung.</p><div class="row"><div><label for="pm">PM-Erfahrung</label><select id="pm"><option value="">Bitte auswählen</option><option value="keine">Keine</option><option value="wenig">Wenig</option><option value="viel">Viel</option></select></div><div><label for="ai">KI-Nutzung</label><select id="ai"><option value="">Bitte auswählen</option><option value="nie">Nie</option><option value="selten">Selten</option><option value="oft">Oft</option></select></div></div><details><summary>Teilnahme- und Datenhinweise</summary><p class="small">Gespeichert werden anonyme Kennung, Erfahrungskategorien, Zeitstempel, Entwürfe, Antworten, KI-Dialoge und Reflexion. Bei KI-Nutzung werden Fallmaterial, Entwurf und Frage an OpenAI übermittelt. Keine Namen, Kontakte oder vertraulichen Daten eingeben. Die Studienleitung erklärt vor der formalen Teilnahme Zweck, Aufbewahrung, Kontakt und Löschfrist. Keine externe Recherche; normaler Taschenrechner erlaubt. Pro Person nur ein Browser-Tab.</p></details><label class="consent"><input type="checkbox" id="consent"><span>Ich habe die Hinweise gelesen und stimme der protokollierten Teilnahme und der beschriebenen KI-Verarbeitung zu.</span></label><button class="primary full-width" id="start">Erste Runde starten · Zeit beginnt →</button>`; }
function material(c) { return `<section class="card materials"><p class="card-number">FALL ${esc(c.id)} · MATERIALIEN</p><h2>${esc(c.title)}</h2><p class="small muted">${esc(c.subtitle)}</p><p class="small">${esc(c.brief)}</p><details open><summary>Rahmenbedingungen</summary><ul>${c.rules.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details><details open><summary>Arbeitspakete · Aufgabe 1</summary><div class="table-wrap"><table><thead><tr><th>Paket</th><th>Tage</th><th>Ressource</th><th>Nach</th></tr></thead><tbody>${c.packages.map(p=>`<tr><td><strong>${esc(p.id)}</strong><br>${esc(p.name)}</td><td>${p.days}</td><td>${esc(p.resources)}</td><td>${esc(p.after.join(', ') || '—')}</td></tr>`).join('')}</tbody></table></div></details>${c.change ? '<details open><summary>Status & Änderungen · Aufgabe 2</summary>' : ''}<p class="small">${c.change ? esc(c.reference_plan) : ''}</p><ul>${(c.change || []).map(x=>`<li>${esc(x)}</li>`).join('')}</ul>${c.change ? '</details>' : ''}<div class="note">${esc(c.deliverables)}</div></section>`; }
function work() {
  const r = active(), index = state.rounds.indexOf(r);
  nav(index+1);
  $('app').innerHTML = `<section class="work-head"><div><p class="eyebrow">Runde ${index+1} / 2 · ${r.condition === 'ai' ? 'KI-Assistenz' : 'Manuelle Bearbeitung'}</p><h1>${esc(state.case.title)}</h1><p class="small muted">Beide Aufgaben innerhalb einer Runde bearbeiten. Ihre Entscheidung zählt.</p></div><div class="timer"><span id="clock">25:00</span><small>verbleibende Zeit</small></div></section><div class="workspace">${material(state.case)}<div><section class="card editor"><div class="toolbar"><h2>Ihr Arbeitsergebnis</h2><span class="badge">${r.condition === 'ai' ? 'MENSCH + KI' : 'MANUELL'}</span></div><p class="small muted">Texte können Tabellenzeilen enthalten. Alle Zeiten als T1, T2 … angeben.</p><label for="plan">01 · Basisplan & Meilensteine</label><textarea id="plan" maxlength="50000" placeholder="Paket | Start | Ende | Verantwortlich\n…\nMeilensteine: …"></textarea><label for="risks">02 · Risiken & angepasster Plan</label><p class="small muted">${r.stage==='plan' ? 'Nach verbindlichem Abschluss des Basisplans werden Ausgangsplan und Änderungen freigegeben. Die 25 Minuten laufen weiter.' : 'Ihr Basisplan ist gesperrt. Verwenden Sie für diese Aufgabe den bereitgestellten Ausgangsplan.'}</p><textarea id="risks" ${r.stage==='plan' ? 'disabled' : ''} maxlength="50000" placeholder="Risiko | Beleg | Priorität | Auswirkung | Maßnahme | Verantwortlich\n…\nAktualisierte Termine / Expressentscheidung / Eskalation: …"></textarea><div class="actions"><button id="save">Jetzt speichern</button><button class="primary" id="submit">${r.stage==='plan' ? 'Basisplan abschließen →' : 'Runde verbindlich abgeben →'}</button></div><p id="save-state" class="save-state" role="status">Auf dem Server gespeichert.</p></section>${r.condition==='ai' ? `<section class="card ai-panel"><p class="card-number">ASSISTENZ · ENTSCHEIDUNG BLEIBT BEI IHNEN</p><h2>Eine zweite Perspektive</h2><p class="small muted">Fallmaterialien und Ihr gespeicherter Entwurf werden mitgesendet. Vorschläge prüfen und selbst in Ihre Antwort übertragen.</p><label for="question">Ihre Frage an die KI</label><textarea id="question" maxlength="4000" placeholder="Prüfe meinen Plan auf Abhängigkeiten und Ressourcenkonflikte."></textarea><div class="actions"><button class="primary" id="ask">KI fragen</button><span class="small" id="ai-status" role="status"></span></div><div id="chat"></div></section>` : `<div class="note">Manuelle Bedingung: KI-Funktionen sind für diese Runde serverseitig gesperrt. Nutzen Sie ausschließlich die bereitgestellten Materialien.</div>`}</div></div>`;
  let draft = r.draft;
  const backup = sessionStorage.getItem(backupKey());
  if (backup) { try { draft = JSON.parse(backup); dirty=true; } catch { /* retain server draft */ } }
  $('plan').value=draft.plan; $('risks').value=draft.risks; $('plan').disabled=r.stage==='risks';
  if (dirty) $('save-state').textContent='Lokaler Entwurf wiederhergestellt; bitte speichern.';
  for (const id of ['plan','risks']) $(id).addEventListener('input', () => {
    dirty=true; sessionStorage.setItem(backupKey(), JSON.stringify(readDraft()));
    $('save-state').textContent='Ungespeicherte Änderungen …';
    clearTimeout(saveTimer); saveTimer=setTimeout(()=>flush().catch(err=>error(err.message)),700);
  });
  bind('save', flush);
  bind('submit', async () => {
    const finishingPlan = active().stage === 'plan';
    if (!confirm(finishingPlan ? 'Basisplan endgültig sperren und Änderungen öffnen? Die Zeit läuft weiter.' : 'Runde endgültig abgeben? Danach können Sie die Antworten nicht mehr ändern.')) return;
    const key=backupKey(), requestContext=context(), requestToken=token, currentGeneration=generation; const payload=readDraft();
    $('submit').disabled=true; $('plan').disabled=true; $('risks').disabled=true;
    try { await flush(); const next=await api(finishingPlan ? 'plan' : 'submit',{...payload,_context:requestContext},requestToken); sessionStorage.removeItem(key); if(generation===currentGeneration){state=next;dirty=false;render();} }
    finally { if ($('submit') && generation===currentGeneration) { $('submit').disabled=false; $('plan').disabled=active()?.stage==='risks'; $('risks').disabled=active()?.stage==='plan'; } }
  });
  bind('ask', async () => {
    const question=$('question').value, currentGeneration=generation, requestContext=context(), requestToken=token;
    $('ask').disabled=true; $('ai-status').textContent='Anfrage läuft …';
    try { await flush(); await api('ai',{question,_context:requestContext},requestToken); if(generation===currentGeneration && $('question')) $('question').value=''; }
    catch(err) { if(generation===currentGeneration) error(err.message); }
    finally {
      if(generation===currentGeneration) {
        const next=await api('session',undefined,requestToken);
        if(generation===currentGeneration) { state=next; if (!active()) render(); else { renderChat(); if($('ask')) $('ask').disabled=false; if($('ai-status')) $('ai-status').textContent=''; } }
      }
    }
  });
  renderChat(); startClock();
}
function readDraft() { return {plan:$('plan').value, risks:$('risks').value}; }
function flush() {
  clearTimeout(saveTimer);
  if (!$('plan') || !active()) return saveChain;
  const payload=readDraft(), key=backupKey(), requestContext=context(), requestToken=token, currentGeneration=generation;
  const action=saveChain.catch(()=>{}).then(async()=>{
    await api('save',{...payload,_context:requestContext},requestToken);
    if (generation===currentGeneration && $('plan') && JSON.stringify(readDraft())===JSON.stringify(payload)) {
      dirty=false; sessionStorage.removeItem(key);
      $('save-state').textContent='Gespeichert · ' + new Date().toLocaleTimeString('de-DE');
    }
  });
  saveChain=action; return action;
}
function renderChat() {
  if (!$('chat')) return;
  $('chat').innerHTML=active().ai_calls.map(c=>`<div class="chat-entry"><strong>Ihre Frage</strong><p>${esc(c.question)}</p><strong>${c.status==='completed' ? 'KI-Vorschlag' : 'Status: '+esc(c.status)}</strong><pre>${esc(c.status==='completed' ? c.answer : c.error || 'Anfrage läuft oder wurde unterbrochen. Nach 90 Sekunden ist ein neuer Versuch möglich.')}</pre></div>`).join('');
}
function startClock() {
  deadline=Date.now() + state.remaining_seconds*1000;
  const update=()=>{
    const seconds=Math.max(0,Math.ceil((deadline-Date.now())/1000));
    if ($('clock')) $('clock').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
    if (seconds===0) { clearInterval(tick); load().catch(err=>error(err.message)); }
  };
  update(); tick=setInterval(update,500);
  poll=setInterval(async()=>{
    try { const next=await api('session'); if (!next.case) { state=next; dirty=false; render(); } else { deadline=Date.now()+next.remaining_seconds*1000; } }
    catch(err) { error('Verbindung unterbrochen. Lokalen Entwurf behalten; erneut speichern. '+err.message); }
  },10000);
}
function between() {
  nav(2);
  const r=state.rounds[0];
  $('app').innerHTML=`<section class="hero"><div><p class="eyebrow">Runde 1 abgeschlossen</p><h1>Ein Moment<br>zum <em>Durchatmen.</em></h1><p class="lead">${r.status==='timed_out' ? 'Die Zeit ist abgelaufen. Der letzte rechtzeitig gespeicherte Stand wurde als unvollständiges Ergebnis gesichert.' : 'Ihr Ergebnis wurde verbindlich gespeichert.'}</p></div></section><section class="card"><h2>Kurze Pause · 3 Minuten</h2><p class="muted">Bitte die erste Aufgabe nicht weiterbearbeiten und Ergebnisse nicht besprechen. Starten Sie die nächste Runde nach der Pause gemeinsam mit der Studienleitung.</p><p>Als Nächstes: <strong>${state.rounds[1].condition==='ai' ? 'KI-Assistenz' : 'manuelle Bearbeitung'}</strong>. Neues Fallmaterial, erneut 25 Minuten.</p><div class="actions"><button class="primary" id="next">Zweite Runde starten →</button><button id="export">Bisherige Ergebnisse herunterladen</button></div></section>`;
  bind('next',async()=>{state=await api('start',{}); dirty=false; render();}); bindExport();
}
function reflection() {
  nav(3);
  $('app').innerHTML=`<section class="hero"><div><p class="eyebrow">Beide Runden beendet</p><h1>Was hat sich<br><em>verändert?</em></h1><p class="lead">Ihre Beobachtungen helfen, die Ergebnisse einzuordnen. Eine schnelle Antwort ist nicht automatisch eine gute Antwort.</p></div></section><div class="grid-two"><section class="card"><h2>Ihre Reflexion</h2>${[['time_spent','Wofür haben Sie die meiste Zeit gebraucht?'],['trust','Welche KI-Aussagen haben Sie geprüft oder verworfen?'],['human_decisions','Welche Entscheidungen müssen bei Menschen bleiben?'],['workload','Wie hat sich die Arbeitsbelastung zwischen den Runden verändert?'],['protocol_deviations','Gab es technische Probleme oder Abweichungen von den Regeln?']].map(([key,label])=>`<label for="${key}">${label}</label><textarea id="${key}" rows="2" maxlength="5000">${esc(state.reflection[key]||'')}</textarea>`).join('')}<div class="actions"><button id="reflect" class="primary">Reflexion speichern</button><span id="reflection-status" role="status" class="small"></span></div></section><section class="card"><div class="done-icon">✓</div><h2>Ergebnisse gesichert</h2><p class="muted small">Die Bewertung erfolgt später anhand einheitlicher Kriterien durch zwei unabhängige Personen.</p><div class="results-grid">${state.rounds.map((r,i)=>`<div class="result"><strong>Runde ${i+1} · ${esc(r.case_id)}</strong><span>${r.status==='submitted' ? 'Abgegeben' : 'Zeitlimit · unvollständig'}<br>${Math.round(r.ended_at-r.started_at)} Sekunden</span></div>`).join('')}</div><button id="export" class="full-width">Eigene Aufzeichnung herunterladen ↓</button><p class="note">${state.pilot ? 'Pilot-Sitzung: Diese Ergebnisse werden standardmäßig aus der formalen Analyse ausgeschlossen.' : 'Die Aufzeichnung enthält nur Ihre eigene Sitzung. Bewahren Sie sie geschützt auf.'}</p><button id="leave">Sitzung verlassen</button></section></div>`;
  bind('reflect',async()=>{const payload={}; for(const key of ['time_spent','trust','human_decisions','workload','protocol_deviations']) payload[key]=$(key).value; await api('reflect',payload); $('reflection-status').textContent='Reflexion gespeichert.';});
  bind('leave',()=>{sessionStorage.removeItem('pm-token'); token=''; state=null; history.replaceState(null,'','/'); render();}); bindExport();
}
function bindExport() { bind('export',async()=>download('pm-lab-'+state.participant+'.json',await api('export'))); }
function render() {
  generation++;
  clearInterval(tick); clearInterval(poll); clearTimeout(saveTimer);
  $('session-label').textContent=state?.participant || 'Studienvorbereitung';
  $('phase-badge').textContent=state && !state.pilot ? 'STUDIE' : 'PILOT';
  if (!state || state.rounds[0].status==='ready') intro();
  else if (active()) work();
  else if (state.rounds[1].status==='ready') between();
  else reflection();
}
async function load() { if(token) state=await api('session'); render(); }
window.addEventListener('beforeunload',event=>{ if(dirty){event.preventDefault();event.returnValue='';} });
(async()=>{try{health=await api('health'); if(token) sessionStorage.setItem('pm-token',token); await load();}catch(err){error(err.message); $('app').innerHTML='<section class="card"><h2>Sitzung nicht erreichbar</h2><p>Server starten oder den Einladungslink prüfen. Ein neuer Pilot verändert keine vorhandenen Ergebnisse.</p><button id="reset">Neuen Pilot öffnen</button></section>';bind('reset',()=>{token='';state=null;sessionStorage.removeItem('pm-token');history.replaceState(null,'','/');intro();});}})();
