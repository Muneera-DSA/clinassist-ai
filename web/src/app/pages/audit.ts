import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Api, errorText } from '../core/api';
import { CitedText, SearchSelect, SearchOption } from '../ui/components';

interface Row { seq: number; kind: string; entity: string; what: string; value: string; by: string; at: string; denied: boolean; }

@Component({
  selector: 'ca-audit',
  imports: [CitedText, SearchSelect],
  template: `
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Audit trail — the Meterless World Model</div>
        <h1>Every request and every action, recorded by Meterless</h1>
        <p>Each run is an event-sourced record in the Meterless World Model: who asked, Scout's decision and contract, and for every
          action (script, Zetaris fetch, Nemotron call, memory lookup) the request, Meterless's approval or refusal, and the result,
          each with provenance. Identity decisions are recorded the same way.</p>
      </div>
      <button class="btn" (click)="load()">Refresh</button>
    </div>
    @if (error()) { <div class="notice bad mb">{{ error() }}</div> }
    <div class="layout">
      <div class="card">
        <div class="card-head"><h2>Runs</h2><span class="badge neutral">{{ shownRuns().length }} / {{ runs().length }}</span></div>
        <div class="card-body find">
          <ca-search-select [options]="runOptions()" [value]="sel()" placeholder="Search runs: question, patient, user, status…" (changed)="open($event)" />
          <input class="input sm" [value]="filter()" (input)="filter.set($any($event.target).value)" placeholder="…or filter the list below" />
        </div>
        <div class="runs">
          @for (r of shownRuns(); track r) {
            <button class="run" [class.sel]="sel() === r" (click)="open(r)">
              <span class="mono small">{{ r }}</span>
              @if (info()[r]; as i) { <span class="rq">{{ i.prompt }}</span><span class="rm">{{ i.user?.role }} · {{ i.mrn }} · {{ i.status }}</span> }
            </button>
          } @empty { <p class="muted small card-body">No matching runs.</p> }
        </div>
      </div>
      <div class="stack">
        @if (header(); as h) {
          <div class="card card-pad">
            <div class="spread"><h2>{{ h.prompt }}</h2>
              <span class="badge" [class.ok]="(h.outcome || '').startsWith('verified') || h.outcome === 'ok'" [class.bad]="h.outcome === 'blocked' || h.outcome === 'error'"
                    [class.review]="h.outcome === 'escalated' || h.outcome === 'clarify'">{{ h.outcome || 'open' }}</span></div>
            <div class="small muted mt">{{ h.user }} ({{ h.role }}) · patient {{ h.patient }} · data path {{ h.data_path }} · {{ rows().length }} World Model events ·
              {{ actionCount() }} actions · {{ refused() }} refused</div>
            @if (h.decision) { <div class="small mt">Scout: <b>{{ h.decision.status }}</b> {{ h.decision.intent || '' }} @if (h.decision.contract_id) { · contract <span class="mono">{{ h.decision.contract_id }}</span> }</div> }
          </div>
        }
        @if (summary()) { <div class="card card-pad"><ca-cited-text [text]="summary()" [mrn]="header()?.patient || ''" /></div> }
        @if (rows().length) {
          <div class="card">
            <div class="card-head"><div><h2>World Model events</h2><p>In order. "by" is the provenance recorded with each event. Click a row for the full event (deep log).</p></div>
              <button class="btn sm" (click)="allOpen.set(!allOpen())">{{ allOpen() ? 'Collapse all' : 'Expand all' }}</button></div>
            <div class="scroll" style="max-height: 640px">
              <table class="t">
                <thead><tr><th>#</th><th>Event</th><th>About</th><th>What</th><th>Value</th><th>By</th></tr></thead>
                <tbody>
                  @for (r of rows(); track r.seq; let k = $index) {
                    <tr [class.deny]="r.denied" class="ev" (click)="toggle(r.seq)">
                      <td class="mono small">{{ open_(r.seq) ? '▾' : '▸' }} {{ r.seq }}</td><td class="small">{{ r.kind }}</td><td class="mono small">{{ r.entity }}</td>
                      <td class="small">{{ r.what }}</td><td class="mono small val">{{ r.value }}</td><td class="small">{{ r.by }}</td>
                    </tr>
                    @if (open_(r.seq)) {
                      <tr class="deep"><td colspan="6">
                        <div class="small muted">Recorded {{ events()[k]?.at }} · event #{{ r.seq }} · {{ r.kind }}</div>
                        <pre class="code">{{ pretty(events()[k]) }}</pre>
                      </td></tr>
                    }
                  }
                </tbody>
              </table>
            </div>
          </div>
        } @else if (sel()) { <div class="skeleton" style="height: 200px"></div> } @else { <div class="card card-pad muted">Select a run.</div> }
      </div>
    </div>
  </div>`,
  styles: [`.layout { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 16px; align-items: start; }
            @media (max-width: 1000px) { .layout { grid-template-columns: 1fr; } }
            .runs { display: flex; flex-direction: column; max-height: 720px; overflow: auto; }
            .run { text-align: left; border: 0; border-bottom: 1px solid var(--line); background: #fff; padding: 8px 14px; cursor: pointer; font-size: 12px; }
            .run:hover { background: var(--surface-2); } .run.sel { background: var(--primary-soft); }
            .val { max-width: 420px; word-break: break-word; }
            tr.deny td { background: var(--high-soft); }
            .find { display: flex; flex-direction: column; gap: 6px; border-bottom: 1px solid var(--line); }
            .run { display: flex; flex-direction: column; gap: 2px; }
            .rq { font-size: 12.5px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
            .rm { font-size: 11px; color: var(--faint); }
            tr.ev { cursor: pointer; } tr.ev:hover td { background: var(--surface-2); }
            tr.deep td { background: #f8fafc; }
            tr.deep pre.code { white-space: pre-wrap; word-break: break-word; max-height: 360px; overflow: auto; font-size: 11.5px; margin: 6px 0 0; }`],
})
export class AuditPage implements OnInit {
  private api = inject(Api);
  readonly runs = signal<string[]>([]);
  readonly sel = signal<string>('');
  readonly events = signal<any[]>([]);
  readonly summary = signal<string>('');
  readonly error = signal<string | null>(null);
  readonly info = signal<Record<string, any>>({});
  readonly filter = signal('');
  readonly expanded = signal<Set<number>>(new Set());
  readonly allOpen = signal(false);
  readonly runOptions = computed<SearchOption[]>(() => this.runs().map((r) => {
    const i = this.info()[r];
    return { value: r, label: i ? i.prompt : r, hint: i ? `${i.user?.role ?? ''} · ${i.mrn} · ${i.status}` : 'page view or job' };
  }));
  readonly shownRuns = computed(() => {
    const w = this.filter().toLowerCase().split(/\s+/).filter(Boolean);
    return this.runs().filter((r) => { const i = this.info()[r];
      const t = `${r} ${i?.prompt ?? ''} ${i?.mrn ?? ''} ${i?.user?.id ?? ''} ${i?.user?.role ?? ''} ${i?.status ?? ''}`.toLowerCase();
      return w.every((x) => t.includes(x)); });
  });
  toggle(seq: number): void { const s = new Set(this.expanded()); s.has(seq) ? s.delete(seq) : s.add(seq); this.expanded.set(s); }
  open_(seq: number): boolean { return this.allOpen() || this.expanded().has(seq); }
  pretty(e: unknown): string { return JSON.stringify(e, null, 2); }

  readonly rows = computed<Row[]>(() => this.events().map((e) => {
    const p = e.payload ?? {};
    return { seq: e.seq, kind: e.kind, entity: (p.id ?? p.about ?? p.from ?? '').replace(/^(request|action):/, ''),
      what: p.predicate ?? p.type ?? '', value: p.value !== undefined ? JSON.stringify(p.value) : JSON.stringify(p.attrs ?? {}).slice(0, 300),
      by: `${p.source?.by ?? ''} (${p.source?.kind ?? ''})`, at: e.at,
      denied: (p.predicate === 'authorization' && p.value?.allowed === false) || (p.predicate === 'status' && p.value === 'denied') };
  }));
  readonly header = computed(() => {
    const ev = this.events();
    const req = ev.find((e) => e.kind === 'upsertEntity' && e.payload?.type === 'request')?.payload?.attrs;
    if (!req) return null;
    const fact = (pred: string) => ev.filter((e) => e.kind === 'assertFact' && e.payload?.predicate === pred).map((e) => e.payload.value).pop();
    return { ...req, decision: fact('scout_decision'), outcome: (fact('outcome') ?? {}).status };
  });
  readonly actionCount = computed(() => this.events().filter((e) => e.kind === 'upsertEntity' && e.payload?.type === 'action').length);
  readonly refused = computed(() => this.events().filter((e) => e.payload?.predicate === 'authorization' && e.payload?.value?.allowed === false).length);

  ngOnInit(): void { this.load(); }

  async load(): Promise<void> {
    try {
      const r = await this.api.meterlessRuns();
      this.runs.set(r.runs);
      this.api.runs().then((list) => this.info.set(Object.fromEntries((list as any[]).map((x) => [x.run_id, x])))).catch(() => undefined);
      this.error.set(null);
      if (r.runs.length && !this.sel()) { this.open(r.runs[0]); }
    } catch (e) { this.error.set(errorText(e)); }
  }

  async open(id: string): Promise<void> {
    this.sel.set(id);
    this.expanded.set(new Set());
    this.events.set([]);
    this.summary.set('');
    try {
      const w = await this.api.meterlessRun(id);
      this.events.set(w.events);
    } catch (e) { this.error.set(errorText(e)); }
    try {
      const saved = await this.api.run(id);
      this.summary.set(saved?.result?.summary ?? '');
    } catch { /* not an agent run */ }
  }
}
