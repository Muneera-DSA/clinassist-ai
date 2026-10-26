import { DatePipe } from '@angular/common';
import { Component, OnInit, inject, signal } from '@angular/core';
import { Api, RunSummary, errorText } from '../core/api';
import { CitedText } from '../ui/components';

@Component({
  selector: 'ca-audit',
  imports: [DatePipe, CitedText],
  template: `
  <div class="page">
    <div class="page-head">
      <div>
        <div class="eyebrow">Step 6 · Audit trail</div>
        <h1>Every request, every step, kept</h1>
        <p>Each run is saved with who asked, what Scout decided, the signed contract, the plan, every tool call, every draft and
          every check. Identity decisions are kept separately, with provenance, in the Meterless World Model.</p>
      </div>
      <button class="btn" (click)="load()">Refresh</button>
    </div>
    @if (error()) { <div class="notice bad">{{ error() }}</div> }
    <div class="layout">
      <div class="card">
        <table class="t">
          <thead><tr><th>When</th><th>Request</th><th>Status</th></tr></thead>
          <tbody>
            @for (r of runs(); track r.run_id) {
              <tr class="click" [class.sel]="sel()?.run_id === r.run_id" (click)="open(r.run_id)">
                <td class="small">{{ r.at | date: 'dd MMM HH:mm:ss' }}<div class="faint">{{ r.user.id }} · {{ r.user.role }}</div></td>
                <td>{{ r.prompt }}<div class="faint small mono">{{ r.mrn }} · {{ r.mode }}{{ r.ai ? ' · AI' : '' }}</div></td>
                <td><span class="badge" [class.ok]="r.status.startsWith('verified')" [class.bad]="r.status === 'blocked' || r.status === 'error' || r.status === 'refused'" [class.review]="r.status === 'escalated' || r.status === 'clarify'">{{ r.status }}</span></td>
              </tr>
            } @empty { <tr><td colspan="3" class="muted">No runs yet. Use “Ask ClinAssist”.</td></tr> }
          </tbody>
        </table>
      </div>
      <div class="card">
        @if (sel(); as s) {
          <div class="card-head"><div><h2>{{ s.prompt }}</h2><p class="mono">{{ s.run_id }} · {{ s.mrn }} · {{ s.user?.id }} ({{ s.user?.role }})</p></div></div>
          <div class="card-body">
            <ol class="steps">
              @for (e of s.events; track $index) {
                <li><span class="mono faint">{{ e.t }}s</span> <b>{{ label(e) }}</b> <span class="muted small">{{ detail(e) }}</span></li>
              }
            </ol>
            @if (s.result?.summary) { <div class="mt"><ca-cited-text [text]="s.result.summary" [mrn]="s.mrn" /></div> }
          </div>
        } @else { <div class="card-body muted">Select a run.</div> }
      </div>
    </div>
  </div>`,
  styles: [`.layout { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.2fr); gap: 16px; align-items: start; }
            @media (max-width: 1100px) { .layout { grid-template-columns: 1fr; } }
            tr.sel td { background: var(--primary-soft); }
            .steps { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 4px; font-size: 13px; max-height: 560px; overflow: auto; }`],
})
export class AuditPage implements OnInit {
  private api = inject(Api);
  readonly runs = signal<RunSummary[]>([]);
  readonly sel = signal<any>(null);
  readonly error = signal<string | null>(null);

  ngOnInit(): void { this.load(); }

  async load(): Promise<void> {
    try {
      const r = await this.api.runs();
      this.runs.set(r);
      if (r.length && !this.sel()) { this.open(r[0].run_id); }
    } catch (e) { this.error.set(errorText(e)); }
  }

  async open(id: string): Promise<void> {
    try { this.sel.set(await this.api.run(id)); } catch (e) { this.error.set(errorText(e)); }
  }

  label(e: any): string {
    if (e.type === 'trace') return `${e.entry.agent} · ${e.entry.action}`;
    if (e.type === 'scout') return `scout · ${e.decision.status}`;
    if (e.type === 'stage') return `data · ${e.stage}`;
    if (e.type === 'result') return `result · ${e.result.status}`;
    return e.type;
  }

  detail(e: any): string {
    const x = e.entry ?? {};
    if (e.type === 'scout') return `${e.decision.intent?.primary ?? ''} ${e.decision.risk?.flags?.join(', ') ?? ''} ${e.decision.contract?.contract_id ?? ''}`;
    if (e.type === 'stage') return e.message ?? `${e.items ?? ''} rows ${e.seconds ?? ''}s`;
    if (x.action === 'plan') return `${x.steps.map((s: any) => s.tool).join(', ')} · ${x.model}`;
    if (x.action === 'tool') return `${x.tool} → ${x.ids} ids`;
    if (x.action === 'draft') return `${x.model} · ${x.seconds}s`;
    if (x.action === 'verdict') return x.passed ? 'passed' : `${x.issues.length} issue(s)`;
    if (x.action === 'contract-check') return x.reason;
    return x.reason ?? x.error ?? x.status ?? '';
  }
}
