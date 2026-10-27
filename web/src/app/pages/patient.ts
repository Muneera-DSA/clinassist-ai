import { DecimalPipe } from '@angular/common';
import { Component, computed, effect, inject, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { Api, PatientReview, Trend, errorText } from '../core/api';
import { AppState, SYSTEM_OF_LINK } from '../core/state';
import { EngineBadge, EvidenceChips, PatientPicker, TrendChart } from '../ui/components';

@Component({
  selector: 'ca-patient',
  imports: [DecimalPipe, RouterLink, EngineBadge, EvidenceChips, PatientPicker, TrendChart],
  template: `
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Longitudinal analysis</div>
        <h1>Three years of one patient's history, evidence on every line</h1>
        <p>Only identity links that were automatic or confirmed by a person are used. Nothing dated after the review date is read.
          Every flag cites the exact source records; click any chip to open the row.</p>
      </div>
      <div class="row"><ca-patient-picker /><button class="btn" (click)="load(true)" [disabled]="loading()">Reload through Zetaris</button></div>
    </div>
    @if (error()) { <div class="notice bad mb">{{ error() }}</div> }
    @if (loading() && !p()) { <div class="card card-pad"><div class="row"><span class="spinner"></span> Reading the record from three systems through Zetaris…</div></div> }

    @if (p(); as r) {
      <div class="card card-pad head">
        <div>
          <h2 style="font-size:19px">{{ r.patient.label }}</h2>
          <div class="muted small">{{ r.patient.mrn }} · review date {{ r.window.as_of }} · look-back from {{ r.window.since }} · rules {{ r.rules_version }}</div>
          <div class="row mt">
            <span class="idchip"><ca-engine system="hospital_ehr" /> <span class="mono">{{ r.patient.mrn }}</span> master</span>
            @for (l of r.identity.linked_records; track l.record_id) {
              <span class="idchip"><ca-engine [system]="sys(l.system)" /> <span class="mono">{{ l.record_id }}</span> {{ l.status === 'linked-by-reviewer' ? 'confirmed by a person' : 'linked' }}</span>
            }
            @for (l of r.identity.pending_review; track l.record_id) {
              <span class="idchip pending"><ca-engine [system]="sys(l.system)" /> <span class="mono">{{ l.record_id }}</span> waiting for review — not used</span>
            }
          </div>
        </div>
        <div class="loadbox">
          <div class="faint small">Loaded {{ r.load.mode === 'zetaris' ? 'through Zetaris' : 'from the offline copy' }}</div>
          <div><b>{{ r.load.items | number }}</b> source rows · <b>{{ r.load.queries.length }}</b> federated queries · <b>{{ r.load.seconds }}s</b></div>
          <div class="faint small">analysis {{ r.load.analysis_seconds }}s</div>
          @if (r.load.queries.length) { <button class="btn sm ghost" (click)="showSql.set(!showSql())">{{ showSql() ? 'Hide' : 'Show' }} the SQL</button> }
        </div>
      </div>
      @if (showSql()) {
        <div class="card card-pad mt stack">
          @for (q of r.load.queries; track $index) {
            <div><div class="row small"><ca-engine [system]="q.system" /><span class="muted">{{ q.table }} · {{ q.rows }} row(s) · {{ q.seconds }}s</span></div><pre class="code mt">{{ q.sql }}</pre></div>
          }
        </div>
      }

      <div class="grid g4 mt">
        <div class="card metric"><div class="label">High-priority flags</div><div class="value" style="color: var(--high)">{{ sev('high') }}</div><div class="note">need a clinician's attention</div></div>
        <div class="card metric"><div class="label">For review</div><div class="value" style="color: var(--review)">{{ sev('review') }}</div><div class="note">grouped to limit alert fatigue</div></div>
        <div class="card metric"><div class="label">Lab results in window</div><div class="value">{{ r.counts['lab_result'] }}</div><div class="note">from the laboratory system</div></div>
        <div class="card metric"><div class="label">Prescriptions</div><div class="value">{{ r.counts['prescription'] }}</div><div class="note">from the pharmacy system</div></div>
      </div>

      <div class="layout mt">
        <div class="stack">
          <div class="card">
            <div class="card-head"><div><h2>Findings</h2><p>Rule-based, each with its guideline source. Prompts for a professional, not diagnoses.</p></div>
              <a class="btn sm primary" routerLink="/ask">Ask the agent about this patient →</a></div>
            <div class="card-body stack">
              @for (f of r.findings; track $index) {
                <div class="finding" [class]="'finding ' + f.severity">
                  <div class="row"><span class="badge" [class]="'badge ' + f.severity">{{ f.severity === 'high' ? 'HIGH' : f.severity }}</span><b>{{ f.title }}</b></div>
                  <div class="small">{{ f.detail }}</div>
                  <div class="row small">
                    @if (srcTitle(r, f.source); as src) {
                      <span class="faint">Source: @if (srcUrl(r, f.source); as u) { <a [href]="u" target="_blank" rel="noopener">{{ src }} ↗</a> } @else { {{ src }} (internal rule) }</span>
                    } @else { <span class="faint">Internal rule</span> }
                  </div>
                  <div><ca-evidence [ids]="f.evidence" [mrn]="r.patient.mrn" [max]="5" /></div>
                </div>
              } @empty { <p class="muted">No rule-based findings for this patient.</p> }
            </div>
          </div>

          <div class="card">
            <div class="card-head"><div><h2>Lab trends</h2><p>Robust Theil–Sen slope per year; green band = guideline range (illustrative).</p></div></div>
            <div class="card-body trends">
              @for (t of trends(); track t.analyte) {
                <div class="trend">
                  <div class="spread"><b>{{ t.label }}</b><span class="badge" [class.high]="t.direction === 'falling'" [class.review]="t.direction === 'rising'" [class.info]="t.direction !== 'falling' && t.direction !== 'rising'">{{ t.direction }}</span></div>
                  <div class="small muted">{{ t.first.value }} → <b>{{ t.latest.value }}</b> {{ t.unit }} · n={{ t.n }}@if (t.slope_per_year !== null) { · {{ t.slope_per_year > 0 ? '+' : '' }}{{ t.slope_per_year }}/yr }</div>
                  <ca-trend-chart [points]="t.points" [band]="t.band" [direction]="t.direction" [label]="t.label" />
                  <div><ca-evidence [ids]="t.evidence" [mrn]="r.patient.mrn" [max]="3" /></div>
                </div>
              }
            </div>
          </div>

          <div class="card">
            <div class="card-head"><div><h2>Medications</h2><p>From the pharmacy system. "Active" but not prescribed in 12 months is flagged as stale.</p></div></div>
            <div class="scroll"><table class="t">
              <thead><tr><th>Medication</th><th>Status</th><th>First</th><th>Last</th><th class="num">In window</th><th>Evidence</th></tr></thead>
              <tbody>
                @for (m of r.medications; track $index) {
                  <tr><td>{{ m.medication }}</td><td><span class="badge" [class.ok]="m.status === 'active'" [class.neutral]="m.status !== 'active'">{{ m.status }}</span></td>
                    <td class="small">{{ m.first_prescribed }}</td><td class="small">{{ m.last_prescribed }}</td><td class="num">{{ m.prescriptions_in_window }}</td>
                    <td><ca-evidence [ids]="m.evidence" [mrn]="r.patient.mrn" [max]="1" /></td></tr>
                }
              </tbody>
            </table></div>
          </div>
        </div>

        <div class="stack">
          <div class="card">
            <div class="card-head"><h2>Timeline</h2></div>
            <div class="card-body"><ol class="tl">
              @for (e of r.timeline; track $index) {
                <li><div class="small faint">{{ e.date }} · {{ e.type }}</div><div>{{ e.text }}</div><ca-evidence [ids]="e.evidence" [mrn]="r.patient.mrn" [max]="2" /></li>
              }
            </ol></div>
          </div>
          <div class="card">
            <div class="card-head"><h2>Allergies</h2></div>
            <div class="card-body">
              @for (a of r.allergies; track $index) { <div class="small"><b>{{ a.substance }}</b> · {{ a.category }} · {{ a.reaction || 'reaction not stated' }}</div> }
              @empty { <p class="muted small">None recorded.</p> }
            </div>
          </div>
          <div class="card">
            <div class="card-head"><h2>Active problems</h2></div>
            <div class="card-body"><ul class="probs">
              @for (c of r.active_conditions; track $index) { <li><span>{{ c.display }}</span> <span class="faint small">since {{ c.onset }}</span></li> }
            </ul></div>
          </div>
        </div>
      </div>
    }
  </div>`,
  styles: [`
    .head { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
    .idchip { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--line); border-radius: 8px; padding: 3px 8px; font-size: 12px; background: var(--surface-2); }
    .idchip.pending { background: #fffaf3; border-color: #f8d7b0; }
    .loadbox { text-align: right; font-size: 13px; }
    .layout { display: grid; grid-template-columns: minmax(0, 2fr) minmax(280px, 1fr); gap: 16px; align-items: start; }
    @media (max-width: 1100px) { .layout { grid-template-columns: 1fr; } }
    .finding { border-left: 4px solid var(--line-strong); padding: 6px 0 6px 12px; display: flex; flex-direction: column; gap: 4px; }
    .finding.high { border-left-color: var(--high); } .finding.review { border-left-color: #f79009; } .finding.info { border-left-color: #98a2b3; }
    .trends { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }
    .trend { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; display: flex; flex-direction: column; gap: 4px; }
    .tl { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 10px; }
    .tl li { border-left: 3px solid var(--primary-soft); padding-left: 10px; }
    .probs { margin: 0; padding-left: 18px; font-size: 13px; max-height: 360px; overflow: auto; }
  `],
})
export class PatientPage {
  readonly state = inject(AppState);
  private api = inject(Api);
  readonly p = signal<PatientReview | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly showSql = signal(false);
  readonly trends = computed<Trend[]>(() => Object.values(this.p()?.trends ?? {}).filter((t) => t.points?.length > 1)
    .sort((a, b) => (b.direction === 'falling' ? 1 : 0) - (a.direction === 'falling' ? 1 : 0)));

  constructor() {
    effect(() => { this.state.mrn(); untracked(() => this.load(false)); });
  }

  async load(fresh: boolean): Promise<void> {
    const mrn = this.state.mrn();
    this.loading.set(true);
    this.error.set(null);
    if (fresh || this.p()?.patient.mrn !== mrn) { this.p.set(null); }
    try {
      const r = await this.api.patient(mrn, fresh);
      if (r.patient.mrn === this.state.mrn()) { this.p.set(r); }
      this.state.refreshPatients();
    } catch (e) { this.error.set(errorText(e)); }
    this.loading.set(false);
  }

  sev(s: string): number { return (this.p()?.findings ?? []).filter((f) => f.severity === s).length; }
  sys(s: string): string { return SYSTEM_OF_LINK[s] ?? s; }
  srcTitle(r: PatientReview, key: string | null): string | null { return key ? (r.sources[key]?.title ?? null) : null; }
  srcUrl(r: PatientReview, key: string | null): string | null { return key ? (r.sources[key]?.url ?? null) : null; }
}
