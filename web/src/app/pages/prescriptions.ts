import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, errorText } from '../core/api';
import { AppState } from '../core/state';
import { EvidenceChips, PatientPicker } from '../ui/components';

interface Flag { rule: string; level: string; title: string; detail: string; source: string | null; source_info?: { key: string; title: string; url: string | null } | null; evidence: string[]; }
interface Label { medication: string; label_title: string; manufacturer: string; matched_by: string; label_version_date: string | null; source_url: string | null; sections: Record<string, string>; }
interface Med {
  medication: string; ingredient: string; rxnorm_code: string; status: 'active' | 'past'; first_prescribed: string | null; last_prescribed: string | null;
  prescriptions: number; prescribers: string[]; dosage_text: string; recent: { date: string | null; status: string; prescriber: string; eid: string }[];
  administrations: number; last_administered: string | null; evidence: string[]; flags: Flag[]; label: Label | null;
}
interface RxView {
  mrn: string; patient: string; as_of: string; medications: Med[]; allergies: any[]; meterless_run: string;
  counts: { medicines: number; active: number; flagged: number; with_label: number };
  labels: { available: boolean; fetched_at: string | null; source: string | null; note: string | null };
}

const SECTION_TITLES: [string, string][] = [
  ['boxed_warning', 'Boxed warning'], ['contraindications', 'Contraindications'], ['warnings', 'Warnings and precautions'],
  ['drug_interactions', 'Drug interactions'], ['adverse_reactions', 'Adverse reactions (side effects)'], ['indications', 'What it is used for'],
];

@Component({
  selector: 'ca-prescriptions',
  imports: [FormsModule, PatientPicker, EvidenceChips],
  template: `
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Medicine review</div>
        <h1>Every medicine, current and past, with what to watch for</h1>
        <p>The full prescription history from the pharmacy system (through Zetaris), our own rule-based safety flags on each medicine,
          and the official US FDA label sections for it: contraindications, warnings, interactions and side effects. Every row cites
          its source record. Label text is reference information, not advice for this patient.</p>
      </div>
    </div>

    <div class="card card-pad row wrap gap">
      <ca-patient-picker />
      <input class="input search" [ngModel]="q" (ngModelChange)="q = $event; qSig.set($event)" placeholder="Find a medicine or ingredient… e.g. metformin, statin" />
      <div class="seg">
        <button class="btn sm" [class.primary]="show() === 'all'" (click)="show.set('all')">All</button>
        <button class="btn sm" [class.primary]="show() === 'active'" (click)="show.set('active')">Active</button>
        <button class="btn sm" [class.primary]="show() === 'flagged'" (click)="show.set('flagged')">Flagged</button>
        <button class="btn sm" [class.primary]="show() === 'past'" (click)="show.set('past')">Past</button>
      </div>
      <button class="btn sm" (click)="load(true)">Refresh</button>
    </div>

    @if (err()) { <div class="notice bad mt">{{ err() }}</div> }
    @if (view(); as v) {
      <div class="grid g4 mt">
        <div class="card metric"><div class="label">Medicines ever prescribed</div><div class="value">{{ v.counts.medicines }}</div></div>
        <div class="card metric"><div class="label">Marked active</div><div class="value">{{ v.counts.active }}</div></div>
        <div class="card metric"><div class="label">With a safety flag</div><div class="value">{{ v.counts.flagged }}</div></div>
        <div class="card metric"><div class="label">With an FDA label</div><div class="value">{{ v.counts.with_label }}</div>
          <div class="note">@if (v.labels.available) { saved {{ (v.labels.fetched_at || '').slice(0, 10) }} } @else { not fetched yet }</div></div>
      </div>
      @if (!v.labels.available) {
        <div class="notice warn small mt">FDA label sections are not loaded yet. Run once, with internet:
          <code>.\\.venv\\Scripts\\python.exe .\\reference\\fetch_drug_labels.py</code></div>
      }
      @if (v.allergies.length) {
        <div class="notice small mt"><b>Recorded allergies:</b> @for (a of v.allergies; track $index) { <span class="badge bad">{{ a.substance || a }}</span> }</div>
      }

      <div class="list mt">
        @for (m of filtered(); track m.medication) {
          <div class="card med" [class.flagged]="m.flags.length">
            <div class="med-head" (click)="toggle(m.medication)">
              <div>
                <div class="row gap-s"><b>{{ m.medication }}</b>
                  <span class="badge" [class.ok]="m.status === 'active'" [class.neutral]="m.status === 'past'">{{ m.status }}</span>
                  @for (f of m.flags; track f.rule) { <span class="badge" [class.bad]="f.level === 'high'" [class.review]="f.level !== 'high'">{{ f.level === 'high' ? 'HIGH' : 'review' }} · {{ short(f.rule) }}</span> }
                </div>
                <div class="small muted">{{ m.ingredient }} · RxNorm {{ m.rxnorm_code }} · prescribed {{ m.prescriptions }}× · {{ m.first_prescribed }} → {{ m.last_prescribed }}
                  @if (m.administrations) { · given {{ m.administrations }}× (last {{ m.last_administered }}) }</div>
              </div>
              <span class="chev">{{ open().has(m.medication) ? '▾' : '▸' }}</span>
            </div>

            @if (open().has(m.medication)) {
              <div class="med-body">
                @if (m.flags.length) {
                  <h4>Safety flags (our rules, from this patient's records)</h4>
                  @for (f of m.flags; track $index) {
                    <div class="flag" [class.high]="f.level === 'high'"><b>{{ f.title }}</b><div class="small">{{ f.detail }}</div>
                      @if (f.source_info; as s) {
                        <div class="small faint">Source: @if (s.url) { <a [href]="s.url" target="_blank" rel="noopener">{{ s.title }} ↗</a> } @else { {{ s.title }} (internal rule) }</div>
                      }
                      <ca-evidence [ids]="f.evidence" [mrn]="v.mrn" [max]="6" /></div>
                  }
                }
                <h4>Prescription history</h4>
                <table class="t small">
                  <thead><tr><th>Date</th><th>Status</th><th>Prescriber</th><th>Source</th></tr></thead>
                  <tbody>@for (r of m.recent; track r.eid) { <tr><td>{{ r.date }}</td><td>{{ r.status }}</td><td>{{ r.prescriber }}</td><td><ca-evidence [ids]="[r.eid]" [mrn]="v.mrn" /></td></tr> }</tbody>
                </table>
                @if (m.prescriptions > m.recent.length) { <div class="small faint">{{ m.prescriptions - m.recent.length }} earlier prescription(s) not shown</div> }
                @if (m.dosage_text) { <div class="small mt"><b>Latest dosage instruction:</b> {{ m.dosage_text }}</div> }

                <h4>FDA label <span class="small muted">(reference information, not advice)</span></h4>
                @if (m.label; as L) {
                  <div class="small muted mb">{{ L.label_title }} @if (L.manufacturer) { · {{ L.manufacturer }} } · matched by {{ L.matched_by }}
                    @if (L.label_version_date) { · label version {{ L.label_version_date }} }
                    @if (L.source_url) { · <a [href]="L.source_url" target="_blank" rel="noopener">full label on DailyMed ↗</a> }</div>
                  @for (s of sections(L); track s[0]) {
                    <details class="sec" [open]="s[0] === 'boxed_warning' || s[0] === 'contraindications'"><summary>{{ s[1] }}</summary><p class="small">{{ L.sections[s[0]] }}</p></details>
                  } @empty { <p class="small muted">The label has none of these sections.</p> }
                } @else {
                  <p class="small muted">No FDA label found for this medicine.@if (!v.labels.available) { (Labels not fetched yet.) }</p>
                }
              </div>
            }
          </div>
        } @empty { <div class="card card-pad muted">No medicine matches “{{ q }}”.</div> }
      </div>
      <div class="small faint mt">Recorded by Meterless: run <span class="mono">{{ v.meterless_run }}</span></div>
    } @else if (!err()) { <div class="skeleton mt" style="height: 300px"></div> }
  </div>`,
  styles: [`
    .wrap { flex-wrap: wrap; } .gap { gap: 10px; } .gap-s { gap: 6px; flex-wrap: wrap; }
    .search { flex: 1 1 260px; }
    .seg { display: flex; gap: 4px; }
    .list { display: flex; flex-direction: column; gap: 8px; }
    .med.flagged { border-left: 4px solid #f79009; }
    .med-head { display: flex; justify-content: space-between; gap: 10px; padding: 12px 14px; cursor: pointer; }
    .med-head:hover { background: var(--surface-2); }
    .chev { color: var(--faint); font-size: 18px; }
    .med-body { padding: 0 14px 14px; border-top: 1px solid var(--line); }
    h4 { margin: 14px 0 6px; font-size: 13px; }
    .flag { border-left: 3px solid var(--review); background: var(--review-soft); padding: 6px 10px; border-radius: 6px; margin-bottom: 6px; }
    .flag.high { border-left-color: var(--high); background: var(--high-soft); }
    .sec { margin-bottom: 4px; } .sec summary { cursor: pointer; font-weight: 600; font-size: 12.5px; }
    .sec p { margin: 4px 0 8px 14px; white-space: pre-wrap; }
    code { font-size: 12px; }
  `],
})
export class PrescriptionsPage {
  readonly state = inject(AppState);
  private api = inject(Api);
  q = '';
  readonly view = signal<RxView | null>(null);
  readonly err = signal<string | null>(null);
  readonly show = signal<'all' | 'active' | 'flagged' | 'past'>('all');
  readonly open = signal<Set<string>>(new Set());
  readonly qSig = signal('');
  readonly filtered = computed(() => {
    const v = this.view();
    if (!v) return [];
    const q = this.qSig().trim().toLowerCase();
    const s = this.show();
    return v.medications.filter((m) =>
      (s === 'all' || (s === 'flagged' ? m.flags.length > 0 : m.status === s)) &&
      (!q || m.medication.toLowerCase().includes(q) || m.ingredient.toLowerCase().includes(q) || (q === 'statin' && /statin/i.test(m.medication))));
  });

  constructor() {
    effect(() => { const m = this.state.mrn(); if (m) { this.load(false); } });
  }

  async load(fresh: boolean): Promise<void> {
    this.err.set(null);
    this.view.set(null);
    try {
      const v = await this.api.prescriptions(this.state.mrn(), fresh);
      this.view.set(v as RxView);
      const first = (v as RxView).medications.find((m) => m.flags.some((f) => f.level === 'high'));
      this.open.set(new Set(first ? [first.medication] : []));
    } catch (e) { this.err.set(errorText(e)); }
  }

  toggle(name: string): void {
    this.open.update((s) => { const n = new Set(s); n.has(name) ? n.delete(name) : n.add(name); return n; });
  }
  sections(L: Label): [string, string][] { return SECTION_TITLES.filter(([k]) => !!L.sections?.[k]); }
  short(rule: string): string {
    return ({ 'renal-alendronate': 'kidney limit', 'renal-metformin': 'kidney limit', 'rx-duplicate': 'same ingredient twice',
      'rx-stale-active': 'stale', 'allergy-match': 'allergy', 'acei-potassium': 'potassium', 'low-bp-on-treatment': 'low BP',
      'rx-opioid-benzo': 'opioid + benzodiazepine', 'rx-raas-dual': 'double BP-hormone blockade', 'rx-nsaid-bleeding': 'NSAID + blood thinner',
      'rx-p2y12-dual': 'two antiplatelets', 'rx-nsaid-kidney': 'kidney-risk trio', 'rx-polypharmacy': 'many medicines', 'rx-beers': 'Beers 65+' } as Record<string, string>)[rule] ?? rule;
  }
}
