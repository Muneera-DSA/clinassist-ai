import { Component, computed, effect, inject, input, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, EvidenceItem, errorText } from '../core/api';
import { AppState, ENGINE_CLASS, ENGINE_SHORT, SYSTEM_LABEL } from '../core/state';

/** Coloured badge naming the database engine behind a source system. */
@Component({
  selector: 'ca-engine',
  template: `<span class="engine" [class]="'engine ' + cls()" [title]="label()">{{ short() }}</span>`,
})
export class EngineBadge {
  readonly system = input.required<string>();
  readonly cls = computed(() => ENGINE_CLASS[this.system()] ?? '');
  readonly short = computed(() => ENGINE_SHORT[this.system()] ?? this.system());
  readonly label = computed(() => `${SYSTEM_LABEL[this.system()] ?? this.system()} runs on ${this.short()}`);
}

/** Evidence ids as clickable chips that open the source record. */
@Component({
  selector: 'ca-evidence',
  template: `@for (e of shown(); track e) {<span class="chip" (click)="state.openEvidence(e, mrn() || state.mrn())" [title]="'Open source record ' + e">{{ short(e) }}</span>}
             @if (more() > 0) {<span class="faint small"> +{{ more() }} more</span>}`,
})
export class EvidenceChips {
  readonly state = inject(AppState);
  readonly ids = input<string[]>([]);
  readonly max = input(4);
  readonly mrn = input<string>('');
  readonly shown = computed(() => this.ids().slice(0, this.max()));
  readonly more = computed(() => this.ids().length - this.shown().length);
  short(e: string): string { return e.replace(/^E-/, '').replace(/-(.{6}).*$/, '-$1…'); }
}

/** Patient selector used on every page, so the whole demo follows one person. */
@Component({
  selector: 'ca-patient-picker',
  imports: [FormsModule],
  template: `
    <label class="field" style="min-width: 300px">
      Patient
      <select class="input" [ngModel]="state.mrn()" (ngModelChange)="state.selectPatient($event)">
        @for (p of sorted(); track p.mrn) {
          <option [value]="p.mrn">{{ p.label }} · {{ p.mrn }}{{ p.pending ? ' · ' + p.pending + ' pending' : '' }}</option>
        }
      </select>
    </label>`,
})
export class PatientPicker {
  readonly state = inject(AppState);
  readonly sorted = computed(() => [...this.state.patients()].sort((a, b) =>
    (a.mrn === 'MRN91862E3E' ? -1 : 0) - (b.mrn === 'MRN91862E3E' ? -1 : 0) || a.label.localeCompare(b.label)));
}

/** Small line chart of a lab series with the guideline band shaded (no chart library needed). */
@Component({
  selector: 'ca-trend-chart',
  template: `
    <svg [attr.viewBox]="'0 0 ' + W + ' ' + H" class="chart" role="img" [attr.aria-label]="label()">
      @if (bandY(); as b) { <rect [attr.x]="P" [attr.y]="b.y" [attr.width]="W - 2 * P" [attr.height]="b.h" fill="#e7f6ee" /> }
      <line [attr.x1]="P" [attr.x2]="W - P" [attr.y1]="H - P" [attr.y2]="H - P" stroke="#e3e8ef" />
      <polyline [attr.points]="line()" fill="none" [attr.stroke]="color()" stroke-width="2" stroke-linejoin="round" />
      @for (d of dots(); track $index) { <circle [attr.cx]="d.x" [attr.cy]="d.y" r="2.4" [attr.fill]="color()"><title>{{ d.t }}</title></circle> }
      <text [attr.x]="P" y="11" class="lbl">{{ max() }}</text>
      <text [attr.x]="P" [attr.y]="H - 3" class="lbl">{{ firstDate() }}</text>
      <text [attr.x]="W - P" [attr.y]="H - 3" class="lbl" text-anchor="end">{{ lastDate() }}</text>
    </svg>`,
  styles: [`.chart { width: 100%; height: 120px; display: block; } .lbl { font-size: 9px; fill: #8a96a8; font-family: var(--sans); }`],
})
export class TrendChart {
  readonly points = input<[string, number][]>([]);
  readonly band = input<string>('');
  readonly direction = input<string>('');
  readonly label = input<string>('');
  readonly W = 320; readonly H = 120; readonly P = 6;
  private range = computed(() => {
    const v = this.points().map((p) => p[1]);
    const lo = Math.min(...v), hi = Math.max(...v);
    const pad = (hi - lo) * 0.1 || Math.abs(hi) * 0.1 || 1;
    return { lo: lo - pad, hi: hi + pad };
  });
  private times = computed(() => this.points().map((p) => Date.parse(p[0])));
  private x(t: number): number { const ts = this.times(); const a = Math.min(...ts), b = Math.max(...ts); return this.P + (b > a ? (t - a) / (b - a) : 0.5) * (this.W - 2 * this.P); }
  private y(v: number): number { const r = this.range(); return 14 + (1 - (v - r.lo) / (r.hi - r.lo)) * (this.H - 14 - this.P - 10); }
  readonly line = computed(() => this.points().map((p, i) => `${this.x(this.times()[i]).toFixed(1)},${this.y(p[1]).toFixed(1)}`).join(' '));
  readonly dots = computed(() => this.points().map((p, i) => ({ x: this.x(this.times()[i]), y: this.y(p[1]), t: `${p[0]}: ${p[1]}` })));
  readonly max = computed(() => this.points().length ? Math.max(...this.points().map((p) => p[1])).toFixed(1) : '');
  readonly firstDate = computed(() => this.points()[0]?.[0] ?? '');
  readonly lastDate = computed(() => this.points()[this.points().length - 1]?.[0] ?? '');
  readonly color = computed(() => this.direction() === 'falling' ? '#b42318' : this.direction() === 'rising' ? '#b54708' : '#0f766e');
  /** Parses bands like "60- mL/min", "4.0-5.5 mmol/L", "-5.7 %". */
  readonly bandY = computed(() => {
    const m = /(-?\d*\.?\d*)\s*-\s*(\d*\.?\d*)/.exec(this.band() || '');
    if (!m || !this.points().length) return null;
    const r = this.range();
    const lo = m[1] === '' ? r.lo : Math.max(r.lo, parseFloat(m[1]));
    const hi = m[2] === '' ? r.hi : Math.min(r.hi, parseFloat(m[2]));
    if (!(hi > lo)) return null;
    const y1 = this.y(hi), y2 = this.y(lo);
    return { y: y1, h: Math.max(0, y2 - y1) };
  });
}

/** Renders a summary whose sentences end in [E-…] citations: each citation becomes a chip. */
@Component({
  selector: 'ca-cited-text',
  imports: [EvidenceChips],
  template: `
    @for (l of lines(); track $index) {
      @if (l.heading) { <h3 class="sum-h">{{ l.text }}</h3> }
      @else { <p class="sum-l" [class.bullet]="l.bullet"><span>{{ l.text }}</span> <ca-evidence [ids]="l.cites" [max]="6" [mrn]="mrn()" /></p> }
    }`,
  styles: [`.sum-h { margin: 2px 0 8px; font-size: 15px; } .sum-l { margin: 0 0 8px; line-height: 1.55; }
            .sum-l.bullet { padding-left: 14px; position: relative; } .sum-l.bullet::before { content: ''; position: absolute; left: 2px; top: 9px; width: 5px; height: 5px; border-radius: 50%; background: #0f766e; }`],
})
export class CitedText {
  readonly text = input('');
  readonly mrn = input('');
  readonly lines = computed(() => this.text().split('\n').filter((l) => l.trim()).map((raw) => {
    const heading = /^\s*#/.test(raw);
    const bullet = /^\s*([-*•]|\d+[.)])\s+/.test(raw);
    const cites: string[] = [];
    const text = raw.replace(/^\s*#+\s*/, '').replace(/^\s*([-*•]|\d+[.)])\s+/, '')
      .replace(/\[([^\]]*E-[^\]]*)\]/g, (_m, g: string) => { g.split(',').map((s) => s.trim()).filter(Boolean).forEach((c) => cites.push(c)); return ''; })
      .trim();
    return { heading, bullet, text, cites };
  }));
}

/** Side drawer showing the exact source row behind an evidence id: system, engine, table, record. */
@Component({
  selector: 'ca-evidence-drawer',
  imports: [EngineBadge],
  template: `
    @if (state.evidence(); as ev) {
      <div class="scrim" (click)="state.closeEvidence()"></div>
      <aside class="drawer card" role="dialog" aria-label="Source record">
        <div class="card-head">
          <div><div class="eyebrow">Source record</div><h2 class="mono" style="font-size:13px">{{ ev.eid }}</h2></div>
          <button class="btn ghost" (click)="state.closeEvidence()" aria-label="Close">✕</button>
        </div>
        <div class="card-body">
          @if (loading()) { <div class="skeleton" style="height:120px"></div> }
          @if (error()) { <div class="notice bad">{{ error() }}</div> }
          @if (item(); as it) {
            <div class="row mb"><ca-engine [system]="it.system" /><span class="muted">{{ it.system }}.{{ it.table }}</span></div>
            <dl class="kv mb">
              <dt>Record id</dt><dd class="mono">{{ it.record_id }}</dd>
              <dt>Kind</dt><dd>{{ it.kind }}</dd>
              <dt>Date</dt><dd>{{ it.when || '—' }}</dd>
            </dl>
            <table class="t"><tbody>
              @for (kv of rows(); track kv[0]) { <tr><td class="muted" style="width:38%">{{ kv[0] }}</td><td class="mono">{{ kv[1] }}</td></tr> }
            </tbody></table>
            <p class="small faint mt">Fetched through Zetaris from the source system. Every statement ClinAssist makes points to a record like this one.</p>
          }
        </div>
      </aside>
    }`,
  styles: [`.scrim { position: fixed; inset: 0; background: rgba(14,26,43,.25); z-index: 40; }
            .drawer { position: fixed; top: 0; right: 0; bottom: 0; width: min(520px, 100vw); z-index: 41; border-radius: 0; overflow: auto; }`],
})
export class EvidenceDrawer {
  readonly state = inject(AppState);
  private api = inject(Api);
  readonly item = signal<EvidenceItem | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly rows = computed(() => Object.entries(this.item()?.row ?? {}).filter(([, v]) => v !== '' && v !== null).map(([k, v]) => [k, String(v)]));

  constructor() {
    effect(() => {
      const ev = this.state.evidence();
      this.item.set(null);
      this.error.set(null);
      if (!ev) return;
      this.loading.set(true);
      this.api.evidence(ev.mrn, ev.eid)
        .then((it) => this.item.set(it))
        .catch((e) => this.error.set(errorText(e)))
        .finally(() => this.loading.set(false));
    });
  }
}

/** Short status line for a check: green/red dot, label and detail. */
@Component({
  selector: 'ca-check',
  template: `<div class="row"><span class="dot" [class.ok]="ok() === true" [class.bad]="ok() === false"></span><b>{{ label() }}</b><span class="muted small">{{ detail() }}</span></div>`,
})
export class Check {
  readonly ok = input<boolean | null>(null);
  readonly label = input('');
  readonly detail = input('');
}
