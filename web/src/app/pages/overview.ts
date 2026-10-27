import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
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
        <div class="facts">
          <div class="fact"><b>3 engines</b><span>SQL Server, MySQL and PostgreSQL in one Zetaris query</span></div>
          <div class="fact"><b>Every action approved</b><span>against a signed Scout contract and recorded by Meterless</span></div>
          <div class="fact"><b>Every sentence cited</b><span>fact-checked against what the scripts returned</span></div>
          <div class="fact"><b>Human decides</b><span>no diagnosis, no prescribing, no automatic submission</span></div>
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
          <ca-check [ok]="st.nightshift.ok" label="Nightshift → Nemotron" [detail]="st.nightshift.ok ? nemotronLanes(st.nightshift.models ?? []) : (st.nightshift.error || '')" />
          @if (more()) {
            <div class="lane-list"><b>All {{ st.nightshift.models?.length ?? 0 }} Nightshift lanes:</b> {{ (st.nightshift.models ?? []).join(', ') }}</div>
          }
          <div class="row mt">
            <button class="btn sm" (click)="more.set(!more())">{{ more() ? 'View less' : 'View more (all lanes)' }}</button>
            <button class="btn sm" (click)="state.refreshStatus(true)">Re-check now</button>
          </div>
        } @else { <div class="skeleton" style="height:150px"></div> }
      </div>
    </section>

    <h2 class="sec">How a request flows</h2>
    <div class="flow-wrap">
    <div class="flow">
      @for (f of flow; track f.title; let i = $index; let last = $last) {
        <div class="fcard" [style.--c]="f.color" [class.on]="f.live === undefined || f.live()" [style.grid-column]="(2 * i + 1)">
          <div class="ftop">
            <span class="ficon" [innerHTML]="f.icon"></span>
            <span class="fnum">{{ (i + 1).toString().padStart(2, '0') }}</span>
          </div>
          <div class="ftitle">{{ f.title }}</div>
          @if (f.title === 'Zetaris') {
            <div class="engines"><ca-engine system="hospital_ehr" /><ca-engine system="lab_lis" /><ca-engine system="pharmacy_rx" /></div>
          }
          @if (f.loop) {
            <div class="loopgrid"><span>Choose</span><span>⇄</span><span>Read</span><span>⇅</span><span></span><span>⇅</span><span>Judge</span><span>⇄</span><span>Write</span></div>
          }
          <div class="ftext">{{ f.text }}</div>
          <div class="ftag">{{ f.tag }}</div>
        </div>
        @if (!last) {
          <div class="conn" [style.grid-column]="(2 * i + 2)" [class.both]="f.next === '⇄'">
            <svg viewBox="0 0 34 24" aria-hidden="true">
              <defs><marker [attr.id]="'ah' + i" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto-start-reverse">
                <path d="M0,0 L7,3.5 L0,7 z" fill="currentColor" /></marker></defs>
              @if (f.next === '⇄') {
                <line x1="3" y1="8" x2="30" y2="8" stroke="currentColor" stroke-width="1.8" [attr.marker-end]="'url(#ah' + i + ')'" />
                <line x1="31" y1="16" x2="4" y2="16" stroke="currentColor" stroke-width="1.8" [attr.marker-end]="'url(#ah' + i + ')'" />
              } @else {
                <line x1="2" y1="12" x2="30" y2="12" stroke="currentColor" stroke-width="2" [attr.marker-end]="'url(#ah' + i + ')'" />
              }
            </svg>
          </div>
        }
      }
      <div class="retry" style="grid-column: 5 / 12">
        <span class="retry-label">↺ Unsupported sentence or failed judge: sent back to Nemotron to rewrite (up to 3 rounds), else escalated to a person</span>
      </div>
    </div>
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
    .hero { display: grid; grid-template-columns: 1.5fr 1fr; gap: 0; overflow: hidden; align-items: stretch; }
    .facts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 22px; }
    .fact { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; background: var(--surface-2); display: flex; flex-direction: column; gap: 2px; }
    .fact b { font-size: 13px; } .fact span { font-size: 12px; color: var(--muted); line-height: 1.4; }
    .lane-list { font-size: 11px; color: var(--muted); max-height: 220px; overflow: auto; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); line-height: 1.5; word-break: break-word; }
    .hero-text { padding: 26px 28px; }
    .hero-text h1 { font-size: 24px; max-width: 760px; }
    .hero-text p { color: var(--muted); max-width: 780px; margin: 10px 0 0; line-height: 1.6; }
    .hero-side { background: var(--surface-2); border-left: 1px solid var(--line); padding: 20px 22px; display: flex; flex-direction: column; gap: 9px; }
    .hs-title { font-size: 11px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
    .sysline { padding-left: 18px; }
    .sec { margin: 28px 0 12px; }
    .flow-wrap { overflow-x: auto; padding-bottom: 4px; }
    .flow { display: grid; grid-template-columns: repeat(6, minmax(140px, 1fr) 34px) minmax(140px, 1fr); row-gap: 0; align-items: stretch; min-width: 1150px; }
    .fcard { --c: #475467; position: relative; display: flex; flex-direction: column; gap: 8px; padding: 14px 13px 13px;
      background: var(--surface); border: 1px solid var(--line-strong); border-radius: 12px; box-shadow: var(--shadow);
      min-height: 236px; transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease; grid-row: 1; }
    .fcard:hover { transform: translateY(-3px); border-color: color-mix(in srgb, var(--c) 45%, var(--line)); box-shadow: 0 10px 22px -14px rgba(16, 24, 40, .35); }
    .fcard:not(.on) { opacity: .6; }
    .ftop { display: flex; align-items: center; justify-content: space-between; }
    .ficon { width: 34px; height: 34px; border-radius: 9px; display: grid; place-items: center; color: var(--c);
      background: color-mix(in srgb, var(--c) 10%, var(--surface)); border: 1px solid color-mix(in srgb, var(--c) 22%, var(--line)); }
    .ficon ::ng-deep svg { width: 18px; height: 18px; }
    .fnum { font-size: 12px; font-weight: 700; color: var(--faint); letter-spacing: .04em; }
    .ftitle { font-weight: 700; font-size: 13.5px; line-height: 1.25; min-height: 34px; color: var(--text); }
    .ftext { font-size: 12px; color: var(--muted); line-height: 1.45; flex: 1; }
    .ftag { align-self: flex-start; font-size: 10px; font-weight: 700; letter-spacing: .05em; text-transform: uppercase; padding: 3px 8px;
      border-radius: 99px; color: var(--muted); background: var(--surface-2); border: 1px solid var(--line); }
    .conn { grid-row: 1; display: grid; place-items: center; color: #98a2b3; }
    .conn svg { width: 34px; height: 24px; overflow: visible; }
    .engines { display: flex; gap: 4px; flex-wrap: wrap; }
    .loopgrid { display: grid; grid-template-columns: auto auto auto; gap: 1px 6px; font-size: 11px; font-weight: 700; color: var(--c);
      text-align: center; justify-content: start; background: var(--surface-2); border: 1px solid var(--line); padding: 6px 8px; border-radius: 8px; }
    .retry { grid-row: 2; position: relative; height: 34px; margin: 0 calc((100% - 102px) / 8); border: 2px dashed #b9c1cd; border-top: 0;
      border-radius: 0 0 12px 12px; display: flex; justify-content: center; }
    .retry::before { content: ''; position: absolute; left: -7px; top: -9px; border: 6px solid transparent; border-bottom: 9px solid #98a2b3; border-top: 0; }
    .retry-label { position: absolute; bottom: -10px; background: var(--bg, #f5f7fa); padding: 0 8px; font-size: 11.5px; color: var(--muted); white-space: nowrap; }
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
  readonly more = signal(false);
  private san = inject(DomSanitizer);
  private svg = (d: string): SafeHtml => this.san.bypassSecurityTrustHtml(`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`);
  readonly flow: { title: string; text: string; tag: string; color: string; icon: SafeHtml; next: string; loop?: boolean; live?: () => boolean }[] = [
    { title: 'Doctor asks the chatbot', tag: 'ClinAssist chat', color: '#6b5bd2', next: '→',
      icon: this.svg('<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>'),
      text: 'Asks in natural language. If the request is unclear, the chat asks back before anything runs.' },
    { title: 'Meterless — the supervisor', tag: 'Meterless', color: '#0f766e', next: '→', live: () => !!this.s()?.meterless?.ok,
      icon: this.svg('<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/>'),
      text: 'Scout checks the request, blocks unsafe ones and signs a 15-minute contract. Every action is approved and recorded in the World Model.' },
    { title: 'Nightshift routes to Nemotron — the boss', tag: 'NVIDIA Nemotron', color: '#4d7c0f', next: '⇄', loop: true, live: () => !!this.s()?.nightshift?.ok,
      icon: this.svg('<path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8"/><circle cx="12" cy="12" r="3"/>'),
      text: 'Nightshift takes each step to the right Nemotron model through its lanes. Nemotron makes every decision.' },
    { title: 'Single-action scripts', tag: 'Python · H-MEM catalog', color: '#475467', next: '⇄',
      icon: this.svg('<polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/>'),
      text: 'Each does one job: fetch, list, trend, check, rank. They report facts; they never decide.' },
    { title: 'Zetaris', tag: 'Zetaris', color: '#2f5fa8', next: '→', live: () => !!this.s()?.zetaris?.ok,
      icon: this.svg('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'),
      text: 'One SQL window over three engines, only for this patient’s linked records.' },
    { title: 'Fact-check', tag: 'Enforced by Meterless', color: '#b45309', next: '→',
      icon: this.svg('<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>'),
      text: 'Every sentence must cite what a script returned. Anything unsupported goes back to Nemotron.' },
    { title: 'Clinician decides', tag: 'Human in charge', color: '#6b5bd2', next: '',
      icon: this.svg('<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>'),
      text: 'Reviews a cited summary and makes the call. No diagnosis, no prescribing by the agent.' },
  ];
  nemotronLanes(models: string[]): string {
    const n = models.filter((m) => m.startsWith('nvidia/nemotron'));
    return `${models.length} lanes · Nemotron: ${n.map((m) => m.replace('nvidia/', '')).join(', ') || 'none'}`;
  }

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
