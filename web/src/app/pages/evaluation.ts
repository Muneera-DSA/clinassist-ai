import { DecimalPipe, PercentPipe } from '@angular/common';
import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Api, errorText } from '../core/api';

@Component({
  selector: 'ca-evaluation',
  imports: [DecimalPipe, PercentPipe],
  template: `
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">How we know it works — and where it doesn't</div>
        <h1>Evaluation on synthetic data</h1>
        <p>Every component was tested against an answer key or with planted errors, with held-out cases kept aside while building.
          These numbers come from the saved result files the evaluation scripts write; they are synthetic-data results, not clinical claims.</p>
      </div>
    </div>
    @if (error()) { <div class="notice bad">{{ error() }}</div> }
    @if (e(); as d) {
      <div class="card">
        <div class="card-head"><div><h2>1 · Identity matching under stress</h2>
          <p>Wrong merges (joining two different people — the dangerous error) across {{ d.headline.datasets.length }} synthetic datasets. Lower is better.</p></div></div>
        <div class="scroll"><table class="t">
          <thead><tr><th>Scenario</th><th class="num">Exact surname + DOB</th><th class="num">World Model built-in name resolver</th><th class="num">ClinAssist matcher (strict)</th><th class="num">ClinAssist: found after review</th><th class="num">ClinAssist: sent to a person</th></tr></thead>
          <tbody>
            @for (r of d.headline.stress; track r.scenario) {
              <tr><td><b>{{ scenarioLabel(r.scenario) }}</b></td>
                <td class="num" [class.bad]="r.exact?.wrong_merges > 0">{{ r.exact?.wrong_merges }}</td>
                <td class="num" [class.bad]="r.world_model?.wrong_merges > 0">{{ r.world_model?.wrong_merges }}</td>
                <td class="num good">{{ r.clinassist?.wrong_merges }}</td>
                <td class="num">{{ r.clinassist?.recall_after_review | percent: '1.0-1' }}</td>
                <td class="num">{{ r.clinassist?.review }} / {{ r.clinassist?.records }}</td></tr>
            }
          </tbody>
        </table></div>
        <div class="card-body small muted">The price of safety: the strict setting sends more cases to a person. In a real hospital the Emirates ID (Malaffi, Riayati) would remove most of them.</div>
      </div>

      <div class="grid g2 mt">
        <div class="card">
          <div class="card-head"><div><h2>2 · Fact-checker: planted mistakes</h2><p>Correct summaries with one planted error at a time, several random seeds.</p></div></div>
          <div class="scroll"><table class="t">
            <thead><tr><th>Planted mistake</th>@for (s of seeds(); track s) { <th class="num">{{ s }}</th> }</tr></thead>
            <tbody>
              @for (m of mutations(); track m) {
                <tr><td>{{ m }}</td>@for (s of seeds(); track s) { <td class="num" [class.bad]="rate(s, m) < .5" [class.good]="rate(s, m) === 1">{{ rate(s, m) | percent: '1.0-0' }}</td> }</tr>
              }
              <tr class="tot"><td><b>Overall caught</b></td>@for (s of seeds(); track s) { <td class="num"><b>{{ d.verifier[s].designed_errors.detection_rate | percent: '1.0-0' }}</b></td> }</tr>
              <tr class="tot"><td><b>Correct summaries wrongly rejected</b></td>@for (s of seeds(); track s) { <td class="num"><b>{{ d.verifier[s].clean.false_alarms }}/{{ d.verifier[s].clean.n }}</b></td> }</tr>
            </tbody>
          </table></div>
          <div class="card-body small muted">Blind spots, reported on purpose: treatment orders worded in new ways ("held-out") and false statements with no number. Planned fix: an AI judge on Nightshift's judge lane.</div>
        </div>

        <div class="card">
          <div class="card-head"><div><h2>3 · Scout: request safety</h2><p>Development set (used while building) vs held-out set (written before the code).</p></div></div>
          <div class="scroll"><table class="t">
            <thead><tr><th></th><th class="num">Development</th><th class="num">Held-out</th></tr></thead>
            <tbody>
              @for (k of scoutKeys; track k[0]) {
                <tr><td>{{ k[1] }}</td><td class="num">{{ fmt(d.scout?.dev?.[k[0]]) }}</td><td class="num"><b>{{ fmt(d.scout?.heldout?.[k[0]]) }}</b></td></tr>
              }
            </tbody>
          </table></div>
          <div class="card-body small muted">Pattern-based, not AI: unclear requests are sent back for clarification rather than guessed. The held-out set was written by the same person who built Scout, so it is not a fully independent test.</div>
        </div>
      </div>

      @if (d.llm_bench; as b) {
        <div class="card mt">
          <div class="card-head"><div><h2>4 · Nemotron through Nightshift: benchmark</h2><p>{{ b.task }}</p></div></div>
          <div class="scroll"><table class="t">
            <thead><tr><th>Lane</th><th class="num">Runs</th><th class="num">Verified AI</th><th class="num">Escalated</th><th class="num">Errors</th><th class="num">Median seconds</th><th>Models that answered</th></tr></thead>
            <tbody>
              @for (l of lanes(b.summary); track l[0]) {
                <tr><td><b>{{ l[0] }}</b></td><td class="num">{{ l[1].runs }}</td><td class="num">{{ l[1].verified_ai }}</td><td class="num">{{ l[1].escalated }}</td><td class="num">{{ l[1].errors }}</td>
                  <td class="num">{{ l[1].median_total_seconds | number: '1.0-1' }}</td><td class="mono small">{{ (l[1].served_models || []).join(', ') }}</td></tr>
              }
            </tbody>
          </table></div>
          <div class="card-body small muted">The first benchmark (26 Oct) found two real problems: the fast lane returned its reasoning together with the answer,
            and the deep lane's provider was not available to our NVIDIA account. Both are now handled in code (answer extraction, lane fallback); re-run
            <span class="mono">eval/bench_llm.py</span> to refresh this table.</div>
        </div>
      }
    }
  </div>`,
  styles: [`.good { color: var(--ok); font-weight: 700; } .bad { color: var(--high); font-weight: 700; } tr.tot td { background: var(--surface-2); }
    .card { min-width: 0; overflow: hidden; }
    .grid > .card { min-width: 0; }
    .scroll { overflow-x: auto; }
    .t th { white-space: normal; vertical-align: bottom; }
    .t td.mono { word-break: break-word; }
    .card-body { line-height: 1.5; }`],
})
export class EvaluationPage implements OnInit {
  private api = inject(Api);
  readonly e = signal<any>(null);
  readonly error = signal<string | null>(null);
  readonly seeds = computed(() => Object.keys(this.e()?.verifier ?? {}).filter((s) => this.e().verifier[s]?.by_mutation).sort());
  readonly mutations = computed(() => {
    const s = this.seeds()[0];
    return s ? Object.keys(this.e().verifier[s].by_mutation) : [];
  });
  readonly scoutKeys: [string, string][] = [
    ['n', 'Requests'], ['pass_rate', 'Handled exactly as expected'], ['unsafe_blocked', 'Unsafe requests blocked'],
    ['safe_wrongly_blocked', 'Normal requests wrongly blocked'], ['approved_intent_correct', 'Normal requests understood'],
    ['approved_sent_to_clarify', 'Normal requests sent to clarify'],
  ];

  async ngOnInit(): Promise<void> {
    try { this.e.set(await this.api.evaluation()); } catch (err) { this.error.set(errorText(err)); }
  }

  rate(seed: string, m: string): number { return this.e()?.verifier?.[seed]?.by_mutation?.[m]?.rate ?? 0; }
  fmt(v: unknown): string { return typeof v === 'number' && v <= 1 && v > 0 && !Number.isInteger(v) ? `${Math.round(v * 100)}%` : String(v ?? '—'); }
  lanes(s: Record<string, any>): [string, any][] { return Object.entries(s ?? {}); }
  scenarioLabel(s: string): string {
    return ({ plain: 'Normal data', twins: 'Look-alike twins', 'out-of-index': 'Real patient missing, look-alike present', namesakes: 'Strangers with the same full name' } as Record<string, string>)[s] ?? s;
  }
}
