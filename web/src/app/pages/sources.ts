import { Component, OnInit, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Api, QueryResult, SourceCounts, SystemsView, errorText } from '../core/api';
import { AppState, SYSTEM_LABEL } from '../core/state';
import { EngineBadge, PatientPicker } from '../ui/components';

interface Preset { label: string; sql: string; why: string; }

@Component({
  selector: 'ca-sources',
  imports: [FormsModule, EngineBadge, PatientPicker],
  template: `
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Solving fragmented data</div>
        <h1>Three organisations, three database engines, one window</h1>
        <p>Each source runs on its own engine with its own read-only account. Zetaris federates them: ClinAssist sends one SQL dialect
          and never copies the data or connects to the databases directly.</p>
      </div>
      <button class="btn" (click)="load(true)" [disabled]="loading()">{{ loading() ? 'Checking…' : 'Re-count through Zetaris' }}</button>
    </div>

    @if (error()) { <div class="notice bad mb">{{ error() }}</div> }
    <div class="grid g3">
      @for (sys of systemKeys; track sys) {
        <div class="card">
          <div class="card-head">
            <div><h2>{{ label(sys) }}</h2><p>{{ counts()?.systems?.[sys]?.engine }} · port {{ counts()?.systems?.[sys]?.port }} · {{ counts()?.systems?.[sys]?.id_type }}</p></div>
            <ca-engine [system]="sys" />
          </div>
          <div class="schema small muted">Zetaris schema <span class="mono">{{ schemaOf(sys) }}</span></div>
          <div class="tbl-wrap"><table class="t counts">
            <colgroup><col class="c-name" /><col class="c-num" /><col class="c-num" /><col class="c-badge" /></colgroup>
            <thead><tr><th>Table</th><th class="num">Zetaris</th><th class="num">File</th><th></th></tr></thead>
            <tbody>
              @for (t of tablesOf(sys); track t.table) {
                <tr><td class="mono" [title]="t.zetaris_name">{{ short(t.zetaris_name) }}</td><td class="num">{{ t.rows_zetaris ?? '—' }}</td><td class="num muted">{{ t.rows_csv ?? '—' }}</td>
                  <td>@if (t.match) { <span class="badge ok">match</span> } @else if (t.rows_zetaris !== null) { <span class="badge bad">diff</span> }</td></tr>
              } @empty { <tr><td colspan="4"><div class="skeleton"></div></td></tr> }
            </tbody>
          </table></div>
        </div>
      }
    </div>
    @if (counts()?.zetaris_ok) {
      <details class="mt sqlnote"><summary class="small muted">All {{ counts()!.tables.length }} tables counted in one federated query in {{ counts()!.seconds }}s · show the SQL</summary>
        <pre class="code">{{ counts()!.sql }}</pre></details>
    }

    <div class="card mt">
      <div class="card-head">
        <div><h2>The same person, as each system stores them</h2>
          <p>Different IDs, name order, capitalisation and date formats, plus typing mistakes. This is why exact matching loses patients.</p></div>
        <ca-patient-picker />
      </div>
      <div class="card-body">
        @if (sysErr()) { <div class="notice bad">{{ sysErr() }}</div> }
        @if (sysView(); as v) {
          <div class="grid g3">
            @for (r of v.records; track r.record_id) {
              <div class="rec" [class.pending]="r.status === 'pending-review'">
                <div class="spread mb"><ca-engine [system]="r.system" />
                  <span class="badge" [class.ok]="r.status === 'linked' || r.status === 'master'" [class.review]="r.status === 'pending-review'" [class.primary]="r.status === 'linked-by-reviewer'">{{ statusLabel(r.status) }}</span></div>
                <dl class="kv">
                  @for (kv of entries(r.row); track kv[0]) { <dt>{{ kv[0] }}</dt><dd class="mono">{{ kv[1] || '—' }}</dd> }
                </dl>
              </div>
            }
          </div>
          @if (v.queries.length) {
            <details class="mt"><summary class="small muted">{{ v.queries.length }} federated queries sent through Zetaris</summary>
              @for (q of v.queries; track $index) { <div class="row small mt"><ca-engine [system]="q.system" /><span class="muted">{{ q.rows }} row(s), {{ q.seconds }}s</span></div><pre class="code">{{ q.sql }}</pre> }
            </details>
          }
        } @else if (!sysErr()) { <div class="skeleton" style="height:120px"></div> }
      </div>
    </div>

    <div class="card mt">
      <div class="card-head"><div><h2>Federated SQL console</h2><p>Read-only. Joins across SQL Server, MySQL and PostgreSQL in one statement, through Zetaris.</p></div></div>
      <div class="card-body stack">
        <div class="row">
          @for (p of presets; track p.label) { <button class="btn sm" (click)="usePreset(p)">{{ p.label }}</button> }
        </div>
        @if (presetWhy()) { <div class="notice small">{{ presetWhy() }}</div> }
        <textarea class="input mono" rows="5" [(ngModel)]="sql" spellcheck="false"></textarea>
        <div class="row"><button class="btn primary" (click)="run()" [disabled]="running()">{{ running() ? 'Running…' : 'Run through Zetaris' }}</button>
          @if (result(); as r) { <span class="muted small">{{ r.row_count }} row(s) in {{ r.seconds }}s</span> }</div>
        @if (qErr()) { <div class="notice bad">{{ qErr() }}</div> }
        @if (result(); as r) {
          <div class="scroll" style="max-height: 340px">
            <table class="t"><thead><tr>@for (c of r.columns; track $index) { <th>{{ c }}</th> }</tr></thead>
              <tbody>@for (row of r.rows; track $index) { <tr>@for (c of row; track $index) { <td class="mono">{{ c }}</td> }</tr> }</tbody></table>
          </div>
        }
      </div>
    </div>
  </div>`,
  styles: [`
    .tbl-wrap { overflow: hidden; }
    .schema { padding: 0 18px 8px; }
    .counts { width: 100%; table-layout: fixed; }
    .counts .c-name { width: auto; } .counts .c-num { width: 64px; } .counts .c-badge { width: 70px; }
    .counts th, .counts td { padding-left: 8px; padding-right: 8px; }
    .counts th { white-space: nowrap; }
    .counts td { vertical-align: middle; }
    .counts td.mono { overflow-wrap: anywhere; }
    .grid.g3 > .card { display: flex; flex-direction: column; }
    .sqlnote pre { white-space: pre-wrap; word-break: break-word; }
    .card-head { flex-wrap: wrap; gap: 10px; }
    .rec { border: 1px solid var(--line); border-radius: 10px; padding: 12px; background: var(--surface-2); }
    .rec.pending { border-color: #f8d7b0; background: #fffaf3; }
    details summary { cursor: pointer; }
  `],
})
export class SourcesPage implements OnInit {
  readonly state = inject(AppState);
  private api = inject(Api);
  short(n: string): string { return (n ?? '').split('.').pop() ?? n; }
  schemaOf(sys: string): string { const t = this.tablesOf(sys)[0]; return t?.zetaris_name?.split('.')[0] ?? sys; }
  readonly systemKeys = ['hospital_ehr', 'lab_lis', 'pharmacy_rx'];
  readonly counts = signal<SourceCounts | null>(null);
  readonly loading = signal(false);
  readonly error = signal<string | null>(null);
  readonly sysView = signal<SystemsView | null>(null);
  readonly sysErr = signal<string | null>(null);
  readonly result = signal<QueryResult | null>(null);
  readonly running = signal(false);
  readonly qErr = signal<string | null>(null);
  readonly presetWhy = signal<string>('');
  sql = '';
  readonly presets: Preset[] = [
    { label: 'One query combines 3 engines',
      why: 'Counts from SQL Server, MySQL and PostgreSQL in a single statement.',
      sql: `SELECT 'hospital patients (SQL Server)' AS item, COUNT(*) AS n FROM hospital_ehr.patients
UNION ALL SELECT 'lab results (MySQL)', COUNT(*) FROM lab_lis.lab_results
UNION ALL SELECT 'pharmacy prescriptions (PostgreSQL)', COUNT(*) FROM pharmacy_rx.prescriptions` },
    { label: 'Exact matching across differently structured sources',
      why: 'The hospital (SQL Server) and the lab (MySQL) store names and birth dates in different structures: given + family name vs SURNAME + forenames, ISO dates vs dd/MM/yyyy. Joining them on exact surname + date of birth finds only 99 of 112 lab patients: 13 would silently lose their lab results. ClinAssist’s matcher recovers them safely.',
      sql: `SELECT COUNT(*) AS exact_matches
FROM hospital_ehr.patients AS hp
INNER JOIN lab_lis.lab_patients AS lp
  ON upper(hp.family_name) = lp.surname
 AND date_format(hp.birth_date, 'dd/MM/yyyy') = lp.dob` },
    { label: 'Lab results for a patient',
      why: 'All lab results for the patient selected above, read from the lab system (MySQL) through Zetaris using the lab’s own patient ID.',
      sql: '' },
    { label: 'Medicines per pharmacy patient',
      why: 'Prescription counts from PostgreSQL, joined to the pharmacy patient register.',
      sql: `SELECT pp.full_name AS patient, COUNT(*) AS prescriptions
FROM pharmacy_rx.prescriptions AS rx
INNER JOIN pharmacy_rx.pharmacy_patients AS pp ON rx.pharm_patient_id = pp.pharm_patient_id
GROUP BY pp.full_name
ORDER BY prescriptions DESC
LIMIT 10` },
  ];
  readonly tablesOf = (sys: string) => (this.counts()?.tables ?? []).filter((t) => t.system === sys);

  constructor() {
    effect(() => {
      const mrn = this.state.mrn();
      this.sysView.set(null);
      this.sysErr.set(null);
      this.api.systemsView(mrn).then((v) => this.sysView.set(v)).catch((e) => this.sysErr.set(errorText(e)));
    });
  }

  ngOnInit(): void {
    this.load(false);
    this.usePreset(this.presets[0]);
  }

  async load(fresh: boolean): Promise<void> {
    this.loading.set(true);
    try {
      const c = await this.api.sources(fresh);
      this.counts.set(c);
      this.error.set(c.zetaris_ok ? null : `Zetaris did not answer: ${c.error ?? 'unknown error'}`);
    } catch (e) { this.error.set(errorText(e)); }
    this.loading.set(false);
  }

  usePreset(p: Preset): void {
    if (p.label === 'Lab results for a patient') {
      const lab = this.sysView()?.records.find((r) => r.system === 'lab_lis' && r.status !== 'pending-review');
      const id = lab?.record_id ?? 'LP4EC4D4E';
      const who = this.sysView()?.label ?? 'a sample lab patient';
      p = { ...p, why: lab ? `All lab results for ${who}, lab patient ${id}, read from MySQL through Zetaris.` : `The selected patient has no linked lab record, so a sample lab patient (${id}) is shown.`,
        sql: `SELECT date_format(collected_at, 'yyyy-MM-dd') AS collected, test_name, value_num, unit, reference_range, status
FROM lab_lis.lab_results
WHERE lab_patient_id = '${id}'
ORDER BY collected_at DESC
LIMIT 200` };
    }
    this.sql = p.sql; this.presetWhy.set(p.why); this.result.set(null); this.qErr.set(null); }

  async run(): Promise<void> {
    this.running.set(true);
    this.qErr.set(null);
    try { this.result.set(await this.api.query(this.sql)); } catch (e) { this.qErr.set(errorText(e)); this.result.set(null); }
    this.running.set(false);
  }

  label(sys: string): string { return SYSTEM_LABEL[sys] ?? sys; }
  entries(row: Record<string, string>): [string, string][] { return Object.entries(row); }
  statusLabel(s: string): string {
    return ({ master: 'master record', linked: 'linked automatically', 'linked-by-reviewer': 'confirmed by reviewer', 'pending-review': 'waiting for a person' } as Record<string, string>)[s] ?? s;
  }
}
