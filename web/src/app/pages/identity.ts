import { Component, OnInit, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { NgTemplateOutlet } from '@angular/common';
import { Api, IdentityLink, IdentityView, ProvenanceEvent, SystemsView, errorText } from '../core/api';
import { AppState, SYSTEM_OF_LINK } from '../core/state';
import { EngineBadge, PatientPicker, SearchSelect, SearchOption } from '../ui/components';

@Component({
  selector: 'ca-identity',
  imports: [FormsModule, NgTemplateOutlet, EngineBadge, PatientPicker, SearchSelect],
  template: `
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Identity resolution</div>
        <h1>Which records belong to the same person, and who decided</h1>
        <p>The matcher scores surname, given name, date of birth and sex, and explains every point. It links automatically only when
          everything agrees exactly and no other patient comes close; anything less goes to a person. Every link and decision is
          written to the Meterless World Model with its provenance.</p>
      </div>
    </div>
    @if (error()) { <div class="notice bad mb">{{ error() }}</div> }

    @if (view(); as v) {
      <div class="grid g4">
        <div class="card metric"><div class="label">Linked automatically</div><div class="value">{{ v.auto_links }}</div><div class="note">of {{ v.total_records }} lab and pharmacy patient records</div></div>
        <div class="card metric"><div class="label">Sent to a person</div><div class="value">{{ v.queue.length }}</div><div class="note">{{ reviewedCount() }} decided so far</div></div>
        <div class="card metric"><div class="label">Wrong merges</div><div class="value">{{ wrongMerges() }}</div><div class="note">checked against the synthetic answer key</div></div>
        <div class="card metric"><div class="label">Exact matching would find</div><div class="value">{{ baseline() }}</div><div class="note">lab patients; the rest silently lose their results</div></div>
      </div>

      <div class="grid g2 mt">
        <div class="card">
          <div class="card-head">
            <div><h2>Review queue</h2><p>Approving or rejecting writes a reviewer decision to the World Model and rebuilds the identity view.</p></div>
            <label class="field" style="width: 200px">Reviewing as<input class="input" [(ngModel)]="reviewer" placeholder="Dr Reviewer" /></label>
          </div>
          <div class="card-body">
            <div class="row mb">
              <button class="btn sm" [class.primary]="filter() === 'pending'" (click)="filter.set('pending')">Waiting ({{ v.queue.length - reviewedCount() }})</button>
              <button class="btn sm" [class.primary]="filter() === 'all'" (click)="filter.set('all')">All ({{ v.queue.length }})</button>
              <button class="btn sm" [disabled]="busy()" (click)="rematch()" title="Runs the matcher again over all three systems through Zetaris, as a job approved and recorded by Meterless">Re-run matching (supervised batch job)</button>
            </div>
            @if (actionMsg()) { <div class="notice ok mb small">{{ actionMsg() }}</div> }
            @if (actionErr()) { <div class="notice bad mb small">{{ actionErr() }}</div> }
            @if (shown().length) {
              <label class="field mb">Record to review ({{ shown().length }})
                <ca-search-select [options]="queueOptions()" [value]="selected() ? selected()!.system + ':' + selected()!.record_id : ''"
                                  placeholder="Search by name, record ID or MRN" (changed)="selKey.set($event)" />
              </label>
            }
            @if (selected(); as l) {
                <div class="qi" [class.done]="l.reviewed">
                  <div class="spread">
                    <div class="row"><ca-engine [system]="sys(l.system)" /><span class="mono small">{{ l.record_id }}</span></div>
                    @if (l.review; as r) { <span class="badge" [class.ok]="r.action === 'approve'" [class.bad]="r.action === 'reject'">{{ r.action === 'approve' ? 'confirmed' : 'rejected' }} by {{ r.by }}</span> }
                    @else { <span class="badge review">waiting for a person</span> }
                  </div>
                  <div class="pair">
                    <div><div class="faint small">This record</div><b>{{ l.record_label }}</b></div>
                    <div class="vs">≟</div>
                    <div><div class="faint small">Suggested hospital patient</div><b>{{ l.hospital_label }}</b> <span class="mono small muted">{{ l.mrn }}</span></div>
                  </div>
                  <div class="scorebar" [title]="'Score ' + l.score + ' (auto-link needs 11.5 and everything exact)'">
                    <div class="fill" [style.width.%]="pct(l.score)"></div>
                    <div class="mark review-mark" [style.left.%]="pct(4)"></div>
                    <div class="mark auto-mark" [style.left.%]="pct(11.5)"></div>
                  </div>
                  <div class="row small muted"><span>score <b>{{ l.score }}</b> / 12.5</span><span>· runner-up {{ l.runner_up_mrn }} at {{ l.runner_up_score }}</span></div>
                  <ul class="reasons">@for (r of l.reasons; track $index) { <li>{{ r }}</li> }</ul>
                  @if (!l.reviewed) {
                    <div class="row">
                      <button class="btn sm ok" (click)="decide(l, 'approve')" [disabled]="busy()">✓ Same person</button>
                      <button class="btn sm danger" (click)="decide(l, 'reject')" [disabled]="busy()">✕ Different people</button>
                      <button class="btn sm ghost" (click)="state.selectPatient(l.mrn!)">Show this patient below</button>
                    </div>
                  }
                </div>
            } @else { <p class="muted">Nothing waiting.</p> }
          </div>
        </div>

        <div class="card">
          <div class="card-head"><div><h2>World Model provenance</h2><p>Every event about this patient and the records linked or proposed to them.</p></div>
            <div class="row"><ca-patient-picker /><button class="btn sm" (click)="provFull.set(true)" title="Open in a large window">⤢ Full screen</button></div></div>
          <div class="card-body">
            <ng-container *ngTemplateOutlet="eventList" />
          </div>
        </div>
      </div>

      <div class="card mt">
        <div class="card-head"><div><h2>Matched records for this patient</h2>
          <p>The same person's ID, name, date of birth and sex in each system, read live through Zetaris. Records waiting for a person are shown too, marked.</p></div>
          <ca-patient-picker /></div>
        <div class="card-body">
          @if (matchErr()) { <div class="notice bad">{{ matchErr() }}</div> }
          @else if (matched().length) {
            <div class="tbl-wrap"><table class="t">
              <thead><tr><th>System</th><th>ID in that system</th><th>Name as stored</th><th>Date of birth as stored</th><th>Sex</th><th>Link</th></tr></thead>
              <tbody>
                @for (m of matched(); track m.id) {
                  <tr [class.pend]="m.status === 'pending-review'">
                    <td><ca-engine [system]="m.system" /></td><td class="mono">{{ m.id }}</td><td>{{ m.name || '—' }}</td>
                    <td class="mono">{{ m.dob || '—' }}</td><td>{{ m.sex || '—' }}</td>
                    <td><span class="badge" [class.ok]="m.status === 'linked' || m.status === 'master'" [class.review]="m.status === 'pending-review'" [class.primary]="m.status === 'linked-by-reviewer'">{{ statusLabel(m.status) }}</span></td>
                  </tr>
                }
              </tbody>
            </table></div>
          } @else { <div class="skeleton" style="height: 90px"></div> }
        </div>
      </div>

      @if (provFull()) {
        <div class="overlay" (click)="provFull.set(false)">
          <div class="sheet card" (click)="$event.stopPropagation()">
            <div class="card-head"><div><h2>World Model provenance</h2><p>{{ events().length }} events for the selected patient</p></div>
              <div class="row"><ca-patient-picker /><button class="btn sm" (click)="provFull.set(false)">✕ Close</button></div></div>
            <div class="card-body sheet-body"><ng-container *ngTemplateOutlet="eventList" /></div>
          </div>
        </div>
      }

      <ng-template #eventList>
            @if (provErr()) { <div class="notice bad">{{ provErr() }}</div> }
            <ol class="events">
              @for (e of events(); track e.seq) {
                <li>
                  <div class="row"><span class="badge neutral mono">#{{ e.seq }}</span><b>{{ describe(e) }}</b></div>
                  <div class="small muted">{{ e.from }}@if (e.to) { → {{ e.to }} }</div>
                  <div class="small">by <b>{{ e.source.by }}</b> ({{ e.source.kind }}) · {{ e.at }}@if (e.confidence !== null && e.confidence !== undefined) { · confidence {{ e.confidence }} }</div>
                  @if (e.attrs?.evidence) { <div class="small faint">{{ e.attrs.evidence.join(' | ') }}</div> }
                  @if (e.attrs?.confirmed_by) { <div class="small">confirmed by {{ e.attrs.confirmed_by }} {{ e.attrs.note ? '— ' + e.attrs.note : '' }}</div> }
                </li>
              } @empty { <div class="skeleton" style="height: 120px"></div> }
            </ol>
      </ng-template>
    } @else if (!error()) { <div class="skeleton" style="height: 300px"></div> }
  </div>`,
  styles: [`
    .tbl-wrap { overflow-x: auto; }
    tr.pend td { background: #fffaf3; }
    .card-head { flex-wrap: wrap; gap: 10px; }
    .overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, .45); z-index: 50; display: grid; place-items: center; padding: 24px; }
    .sheet { width: min(1200px, 96vw); height: 90vh; display: flex; flex-direction: column; overflow: hidden; }
    .sheet-body { overflow: auto; flex: 1; }
    .sheet-body .events { max-height: none; }
    .qi { border: 1px solid var(--line); border-radius: 10px; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
    .qi.done { background: var(--surface-2); }
    .pair { display: grid; grid-template-columns: 1fr auto 1fr; gap: 10px; align-items: center; }
    .vs { color: var(--faint); font-size: 18px; }
    .scorebar { position: relative; height: 8px; background: #eef1f5; border-radius: 99px; }
    .scorebar .fill { position: absolute; left: 0; top: 0; bottom: 0; background: #f79009; border-radius: 99px; }
    .scorebar .mark { position: absolute; top: -3px; bottom: -3px; width: 2px; }
    .review-mark { background: #98a2b3; } .auto-mark { background: var(--primary); }
    .reasons { margin: 0; padding-left: 18px; font-size: 12.5px; color: var(--muted); }
    .events { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; max-height: 620px; overflow: auto; }
    .events li { border-left: 3px solid var(--primary-soft); padding: 2px 0 2px 12px; }
  `],
})
export class IdentityPage implements OnInit {
  readonly state = inject(AppState);
  private api = inject(Api);
  readonly view = signal<IdentityView | null>(null);
  readonly error = signal<string | null>(null);
  readonly filter = signal<'pending' | 'all'>('pending');
  readonly busy = signal(false);
  readonly actionMsg = signal<string | null>(null);
  readonly actionErr = signal<string | null>(null);
  readonly events = signal<ProvenanceEvent[]>([]);
  readonly provErr = signal<string | null>(null);
  reviewer = 'Dr Demo Reviewer';
  readonly provFull = signal(false);
  readonly selKey = signal<string>('');
  readonly selected = computed(() => {
    const list = this.shown();
    return list.find((l) => `${l.system}:${l.record_id}` === this.selKey()) ?? list[0] ?? null;
  });
  readonly queueOptions = computed<SearchOption[]>(() => this.shown().map((l) => ({
    value: `${l.system}:${l.record_id}`,
    label: `${l.reviewed ? '✓ ' : ''}${this.sysName(l.system)} ${l.record_id} · ${l.record_label} → ${l.hospital_label ?? ''} ${l.mrn ?? ''}`,
    hint: `score ${l.score}` })));
  readonly sysView = signal<SystemsView | null>(null);
  readonly matchErr = signal<string | null>(null);
  readonly matched = computed(() => (this.sysView()?.records ?? []).map((r) => {
    const x = r.row;
    if (r.system === 'hospital_ehr') return { system: r.system, id: r.record_id, name: `${x['family_name'] ?? ''}, ${x['given_name'] ?? ''}`, dob: x['birth_date'], sex: x['sex'], status: r.status };
    if (r.system === 'lab_lis') return { system: r.system, id: r.record_id, name: `${x['surname'] ?? ''}, ${x['forenames'] ?? ''}`, dob: x['dob'], sex: x['gender'], status: r.status };
    return { system: r.system, id: r.record_id, name: x['full_name'], dob: x['birth_date'], sex: x['sex'], status: r.status };
  }));

  readonly reviewedCount = computed(() => (this.view()?.queue ?? []).filter((l) => l.reviewed).length);
  readonly shown = computed(() => (this.view()?.queue ?? []).filter((l) => this.filter() === 'all' || !l.reviewed));
  readonly wrongMerges = computed(() => {
    const s = this.view()?.report?.systems ?? {};
    return Object.values(s).reduce((a: number, x: any) => a + (x?.accuracy?.auto_link_wrong_merges ?? 0), 0);
  });
  readonly baseline = computed(() => {
    const lab = this.view()?.report?.systems?.laboratory;
    return lab ? `${lab.baseline_exact_links} / ${lab.records}` : '—';
  });

  constructor() {
    effect(() => {
      const mrn = this.state.mrn();
      this.events.set([]);
      this.provErr.set(null);
      this.api.provenance(mrn).then((p) => this.events.set(p.events)).catch((e) => this.provErr.set(errorText(e)));
      this.sysView.set(null);
      this.matchErr.set(null);
      this.api.systemsView(mrn).then((v) => this.sysView.set(v)).catch((e) => this.matchErr.set(errorText(e)));
    });
  }

  ngOnInit(): void { this.load(); }

  async load(): Promise<void> {
    try { this.view.set(await this.api.identity()); } catch (e) { this.error.set(errorText(e)); }
  }

  async decide(l: IdentityLink, action: 'approve' | 'reject'): Promise<void> {
    if (!this.reviewer.trim()) { this.actionErr.set('Enter your name first: every decision needs a named person.'); return; }
    this.busy.set(true);
    this.actionErr.set(null);
    this.actionMsg.set(null);
    try {
      const r = await this.api.review({ system: l.system, record_id: l.record_id, action, by: this.reviewer.trim() });
      this.actionMsg.set(`${action === 'approve' ? 'Confirmed' : 'Rejected'}: ${l.record_id} ${action === 'approve' ? '→' : '≠'} ${l.mrn}. ` +
        `World Model rebuilt (${r.summary?.events ?? '?'} events, ${r.summary?.pending_review ?? '?'} still waiting).`);
      this.selKey.set('');
      await this.load();
      if (l.mrn) { this.state.selectPatient(l.mrn); }
      await this.state.refreshPatients();
    } catch (e) { this.actionErr.set(errorText(e)); }
    this.busy.set(false);
  }

  async rematch(): Promise<void> {
    if (!this.reviewer.trim()) { this.actionErr.set('Enter your name first: a named person must start the matching job.'); return; }
    this.busy.set(true);
    this.actionErr.set(null);
    this.actionMsg.set('Matching job running under Meterless supervision...');
    try {
      const r = await this.api.rematch(this.reviewer.trim());
      this.actionMsg.set(`Matching re-run and recorded by Meterless (run ${r.meterless_run}). World Model: ${r.summary?.events ?? '?'} events, ` +
        `${r.summary?.pending_review ?? '?'} links waiting for review.`);
      await this.load();
      await this.state.refreshPatients();
    } catch (e) { this.actionErr.set(errorText(e)); this.actionMsg.set(null); }
    this.busy.set(false);
  }

  sys(s: string): string { return SYSTEM_OF_LINK[s] ?? s; }
  sysName(s: string): string { return ({ laboratory: 'Lab', pharmacy: 'Pharmacy' } as Record<string, string>)[s] ?? s; }
  statusLabel(s: string): string {
    return ({ master: 'hospital master record', linked: 'linked automatically', 'linked-by-reviewer': 'confirmed by reviewer', 'pending-review': 'waiting for a person' } as Record<string, string>)[s] ?? s;
  }
  pct(score: number | null): number { return Math.max(0, Math.min(100, ((score ?? 0) / 12.5) * 100)); }
  describe(e: ProvenanceEvent): string {
    if (e.kind === 'upsertEntity') return `Record registered (${e.type})`;
    if (e.kind === 'relate') return e.type === 'same_person_as' ? 'Linked: same person' : 'Proposed: possibly the same person';
    if (e.kind === 'assertFact') return `Status: ${e.value}`;
    return e.kind;
  }
}
