import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api } from '../core/api';
import { AppState } from '../core/state';
import { Check, EngineBadge } from '../ui/components';

@Component({
  selector: 'ca-overview',
  imports: [RouterLink, Check, EngineBadge],
  template: `
  <div class="page">
    <section class="hero card">
      <div class="hero-text">
        <div class="eyebrow">Open Agent Hackathon 2026 · Reasoning Architecture</div>
        <h1>A patient's story is split across systems that don't talk to each other.</h1>
        <p>The hospital, the outside laboratory and the pharmacy each keep their own records, on different databases, with
          different patient numbers and differently written names. When a doctor asks a question, <b>Meterless</b> supervises
          everything: <b>Scout</b> checks the request and signs a contract, then every action is approved against that contract
          and recorded in the <b>Meterless World Model</b>. <b>NVIDIA Nemotron</b> (through <b>Meterless Nightshift</b>) leads
          the analysis: it chooses which single-purpose scripts to run, reads their results, decides what they mean and writes
          the answer. Data comes only through <b>Zetaris</b>. A fact-check and a second Nemotron reviewer verify every sentence.
          It never diagnoses or prescribes.</p>
        <div class="row mt">
          <a class="btn primary" routerLink="/ask">Run the agent live →</a>
          <a class="btn" routerLink="/sources">Start the guided demo</a>
        </div>
      </div>
      <div class="hero-side">
        <div class="hs-title">Live system check</div>
        @if (s(); as st) {
          <ca-check [ok]="st.zetaris.ok" label="Zetaris federation" [detail]="st.zetaris.ok ? (st.zetaris.seconds + 's, 3 engines in one query') : (st.zetaris.error || '')" />
          @for (k of systemKeys; track k) {
            <div class="row sysline"><span class="dot" [class.ok]="!!st.zetaris.patients?.[k]" [class.bad]="!st.zetaris.ok"></span>
              <ca-engine [system]="k" /><span class="muted small">{{ st.systems[k]?.label }} · {{ st.zetaris.patients?.[k] ?? '—' }} patients</span></div>
          }
          <ca-check [ok]="!!st.meterless?.ok" label="Meterless supervisor (gateway)" [detail]="st.meterless?.ok ? ('World Model + H-MEM · ' + (st.meterless?.catalog ?? 0) + ' scripts in memory · ' + (st.meterless?.lessons ?? 0) + ' lessons') : (st.meterless?.error || 'not running')" />
          <ca-check [ok]="!!st.world_model.ok" label="Meterless World Model (identity)" [detail]="(st.world_model.events ?? 0) + ' events · ' + (st.world_model.pending_review ?? 0) + ' links awaiting review'" />
          <ca-check [ok]="st.scout.ok" label="Scout" [detail]="st.scout.intents.length + ' intents · ' + st.scout.signing_key + ' signing key'" />
          <ca-check [ok]="st.nightshift.ok" label="Nightshift → Nemotron" [detail]="st.nightshift.ok ? ((st.nightshift.models?.length ?? 0) + ' lanes: ' + (st.nightshift.models ?? []).join(', ')) : (st.nightshift.error || '')" />
          <button class="btn sm mt" (click)="state.refreshStatus(true)">Re-check now</button>
        } @else { <div class="skeleton" style="height:150px"></div> }
      </div>
    </section>

    <h2 class="sec">How a request flows</h2>
    <div class="flow">
      <div class="node person"><div class="nt">Doctor</div><div class="nd">Asks in plain words in the ClinAssist UI.</div></div>
      <div class="arrow">→</div>
      <div class="node sup" [class.live]="s()?.meterless?.ok">
        <div class="nt">Meterless — the supervisor</div>
        <div class="nd"><b>Scout</b> understands the request, blocks unsafe ones and signs a 15-minute contract. Every later action
          is approved against it and recorded (request → approval → result) in the <b>World Model</b>. Nothing runs without it.</div>
      </div>
      <div class="arrow">→</div>
      <div class="node loop" [class.live]="s()?.nightshift?.ok">
        <div class="nt">Nemotron — the boss</div>
        <div class="loopgrid"><span>Choose scripts</span><span>⇄</span><span>Read results</span><span>⇅</span><span></span><span>⇅</span><span>Judge</span><span>⇄</span><span>Write</span></div>
        <div class="nd">Through Nightshift. The script catalog comes from Meterless H-MEM memory. Nemotron makes every decision.</div>
      </div>
      <div class="arrow">⇄</div>
      <div class="node live"><div class="nt">Single-action scripts</div><div class="nd">Each does one thing: fetch, list, trend, check a criterion, rank. They report facts; they don't decide.</div></div>
      <div class="arrow">⇄</div>
      <div class="node" [class.live]="s()?.zetaris?.ok">
        <div class="nt">Zetaris</div>
        <div class="engines"><ca-engine system="hospital_ehr" /><ca-engine system="lab_lis" /><ca-engine system="pharmacy_rx" /></div>
        <div class="nd">One SQL window over three engines, only for this patient's linked records.</div>
      </div>
      <div class="arrow">→</div>
      <div class="node"><div class="nt">Fact-check</div><div class="nd">Enforced by Meterless: every sentence must cite what a script returned; misses go back to Nemotron.</div></div>
      <div class="arrow">→</div>
      <div class="node person"><div class="nt">Clinician</div><div class="nd">Reviews a cited summary. Decides.</div></div>
    </div>

    <h2 class="sec">Results on our synthetic test data</h2>
    <div class="grid g4">
      <div class="card metric"><div class="label">Wrong patient merges</div><div class="value">0</div><div class="note">in 4 stress scenarios × 4 datasets (strict setting)</div></div>
      <div class="card metric"><div class="label">Planted summary errors caught</div><div class="value">{{ detection() }}</div><div class="note">correct summaries rejected: {{ falseAlarms() }}</div></div>
      <div class="card metric"><div class="label">Unsafe requests that reached the agent</div><div class="value">{{ unsafe() }}</div><div class="note">held-out requests written before the code</div></div>
      <div class="card metric"><div class="label">Tables identical through Zetaris</div><div class="value">{{ tablesOk() }}</div><div class="note">rows, keys and value sums vs source files</div></div>
    </div>
    <p class="small faint mt">All figures are on synthetic (Synthea) data with a demonstration rule set not validated by a clinician. They show the engineering works as designed; they are not clinical accuracy claims.</p>

    <h2 class="sec">Demo path (about 4 minutes)</h2>
    <div class="grid g3">
      @for (d of demo; track d.path; let i = $index) {
        <a class="card card-pad demo" [routerLink]="d.path">
          <div class="row"><span class="num-badge">{{ i + 1 }}</span><b>{{ d.title }}</b></div>
          <p class="muted small">{{ d.text }}</p>
        </a>
      }
    </div>
  </div>`,
  styles: [`
    .hero { display: grid; grid-template-columns: 1.6fr 1fr; gap: 0; overflow: hidden; }
    .hero-text { padding: 26px 28px; }
    .hero-text h1 { font-size: 24px; max-width: 760px; }
    .hero-text p { color: var(--muted); max-width: 780px; margin: 10px 0 0; line-height: 1.6; }
    .hero-side { background: var(--surface-2); border-left: 1px solid var(--line); padding: 20px 22px; display: flex; flex-direction: column; gap: 9px; }
    .hs-title { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
    .sysline { padding-left: 18px; }
    .sec { margin: 28px 0 12px; }
    .flow { display: flex; align-items: stretch; gap: 6px; overflow-x: auto; padding-bottom: 6px; }
    .node { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 12px; min-width: 150px; flex: 1; box-shadow: var(--shadow); border-top: 3px solid var(--line-strong); }
    .node.live { border-top-color: var(--primary); }
    .node.src { border-top-color: var(--accent); min-width: 190px; }
    .node.person { border-top-color: #7a5af8; }
    .node.loop { min-width: 210px; }
    .node.sup { min-width: 240px; border-color: var(--primary); }
    .nt { font-weight: 700; font-size: 13px; margin-bottom: 6px; }
    .nd { font-size: 12px; color: var(--muted); line-height: 1.45; }
    .engines { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 6px; }
    .arrow { align-self: center; color: var(--faint); font-size: 18px; }
    .loopgrid { display: grid; grid-template-columns: auto auto auto; gap: 2px 6px; font-size: 11.5px; font-weight: 650; color: var(--primary); margin-bottom: 6px; text-align: center; }
    .demo { color: inherit; text-decoration: none; transition: border-color .15s; }
    .demo:hover { border-color: var(--primary); text-decoration: none; }
    .demo p { margin: 6px 0 0; }
    .num-badge { width: 22px; height: 22px; border-radius: 50%; background: var(--primary-soft); color: var(--primary); display: grid; place-items: center; font-weight: 700; font-size: 12px; }
    @media (max-width: 1000px) { .hero { grid-template-columns: 1fr; } .hero-side { border-left: 0; border-top: 1px solid var(--line); } }
  `],
})
export class OverviewPage implements OnInit {
  readonly state = inject(AppState);
  private api = inject(Api);
  readonly s = this.state.status;
  readonly systemKeys = ['hospital_ehr', 'lab_lis', 'pharmacy_rx'];
  readonly evalData = signal<any>(null);
  readonly sources = signal<any>(null);
  readonly detection = computed(() => {
    const d: number[] = this.evalData()?.headline?.verifier_detection ?? [];
    return d.length ? `${Math.round(Math.min(...d) * 100)}–${Math.round(Math.max(...d) * 100)}%` : '—';
  });
  readonly falseAlarms = computed(() => (this.evalData()?.headline?.verifier_false_alarms ?? []).slice(-1)[0] ?? '—');
  readonly unsafe = computed(() => {
    const h = this.evalData()?.scout?.heldout;
    if (!h) return '—';
    const n = Number(String(h.unsafe_blocked).split('/')[1]);
    const reached = (h.misses ?? []).filter((m: any) => m.expect === 'blocked' && m.got?.status === 'approved').length;
    return `${reached} / ${n}`;
  });
  readonly tablesOk = computed(() => {
    const t = this.sources()?.tables as { match: boolean }[] | undefined;
    return t ? `${t.filter((x) => x.match).length} / ${t.length}` : '—';
  });
  readonly demo = [
    { path: '/sources', title: 'Fragmented data, one window', text: 'Three engines, one federated query. The same man written three different ways.' },
    { path: '/identity', title: 'Who is who, safely', text: 'Scores and reasons for every link; a person confirms the uncertain ones in the World Model.' },
    { path: '/patient', title: 'Three years, evidence-linked', text: 'Kidney decline, unsafe medicine, missing tests: every flag opens its source record.' },
    { path: '/ask', title: 'Ask, and watch it reason', text: 'Meterless approves, Nemotron picks the scripts and decides, the fact-check verifies or sends it back.' },
    { path: '/ask', title: 'Try to break it', text: 'A prompt injection, a prescribing request, another patient: Scout stops them before the agent runs.' },
    { path: '/audit', title: 'Every step on record', text: 'The Meterless World Model shows each request, approval, refusal and result.' },
    { path: '/evaluation', title: 'How we know', text: 'Stress tests, planted errors, held-out requests, and the blind spots we found.' },
  ];

  async ngOnInit(): Promise<void> {
    this.api.evaluation().then((e) => this.evalData.set(e)).catch(() => undefined);
    this.api.sources().then((s) => this.sources.set(s)).catch(() => undefined);
  }
}
