import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

// ---------------------------------------------------------------- types (mirror server/services.py)
export interface SystemInfo { label: string; engine: string; port: number; id_type: string; }
export interface Status {
  checked_at: string; mode: 'zetaris' | 'csv'; as_of: string; years: number; rules_version: string;
  zetaris: { ok: boolean; seconds: number; error?: string; patients?: Record<string, number> };
  nightshift: { ok: boolean; seconds: number; error?: string; models?: string[]; fast?: string; deep?: string };
  world_model: { ok: boolean; error?: string; patients?: number; linked_records?: number; pending_review?: number; events?: number; audit_entries?: number; built_from?: string };
  scout: { ok: boolean; registry_version: string; intents: string[]; lanes: Record<string, string>; signing_key: string };
  meterless?: { ok: boolean; error?: string; engines?: string[]; catalog?: number; lessons?: number };
  systems: Record<string, SystemInfo>;
}
export interface TableCount { system: string; table: string; zetaris_name: string; rows_zetaris: number | null; rows_csv: number | null; match: boolean; }
export interface SourceCounts { systems: Record<string, SystemInfo>; tables: TableCount[]; zetaris_ok: boolean; seconds?: number; sql?: string; error?: string; }
export interface QueryResult { columns: string[]; rows: unknown[][]; row_count: number; seconds: number; }
export interface ZQuery { sql: string; table: string; system: string; engine: string; rows: number; seconds: number; }
export interface PatientListItem { mrn: string; label: string; linked: number; pending: number; systems: string[]; loaded: boolean; findings: Record<string, number> | null; }
export interface Finding { rule: string; severity: 'high' | 'review' | 'info'; title: string; detail: string; evidence: string[]; source: string | null; }
export interface Trend {
  analyte: string; label: string; unit: string; n: number; first: { date: string; value: number; eid: string }; latest: { date: string; value: number; eid: string };
  min: number; max: number; slope_per_year: number | null; change_pct: number | null; direction: string; above_band: number; below_band: number;
  band: string; evidence: string[]; points: [string, number][]; series?: string;
}
export interface Medication { medication: string; ingredient: string; status: string; first_prescribed: string; last_prescribed: string; prescriptions: number; prescriptions_in_window: number; evidence: string[]; }
export interface TimelineEvent { date: string; type: string; text: string; evidence: string[]; }
export interface EvidenceItem { eid?: string; system: string; engine: string; table: string; record_id: string; kind: string; when: string | null; row: Record<string, unknown>; }
export interface LinkRef { system: string; record_id: string; status: string; }
export interface PatientReview {
  patient: { mrn: string; label: string; birth_date: string; sex: string; deceased_at: string | null };
  window: { as_of: string; since: string };
  identity: { linked_records: LinkRef[]; pending_review: LinkRef[] };
  counts: Record<string, number>;
  allergies: { substance: string; category: string; reaction: string; criticality: string; evidence: string[] }[];
  active_conditions: { display: string; onset: string | null; evidence: string[] }[];
  trends: Record<string, Trend>; medications: Medication[]; findings: Finding[]; timeline: TimelineEvent[];
  rules_version: string; sources: Record<string, { title: string; url?: string }>;
  evidence: Record<string, EvidenceItem>;
  load: { mode: string; loaded_at: string; seconds: number; analysis_seconds: number; queries: ZQuery[]; items: number };
}
export interface SystemsView { mrn: string; label: string; mode: string; queries: ZQuery[]; records: { system: string; engine: string; record_id: string; status: string; row: Record<string, string> }[]; }
export interface IdentityLink { system: string; record_id: string; record_label: string; decision: string; mrn: string | null; hospital_label: string | null; score: number | null; runner_up_mrn: string | null; runner_up_score: number | null; reasons: string[]; reviewed?: boolean; review?: ReviewDecision | null; }
export interface ReviewDecision { system: string; record_id: string; mrn: string; action: string; by: string; at: string; note?: string; }
export interface IdentityView { report: any; queue: IdentityLink[]; decisions: ReviewDecision[]; world: Record<string, any>; auto_links: number; total_records: number; }
export interface ProvenanceEvent { seq: number; at: string; kind: string; type: string; from: string; to: string | null; value: unknown; confidence: number | null; attrs: any; source: { kind: string; by: string; at: string; runId: string }; }
export interface ScoutDecision {
  status: 'approved' | 'clarify' | 'blocked'; message: string;
  intent: { primary: string | null; confidence: number; secondary: string[] };
  risk: { level: string; flags: string[]; matched: string[] };
  plan: { tool: string; args: Record<string, unknown> }[]; lanes: Record<string, string>;
  contract: any | null; telemetry: any; contract_check?: { ok: boolean; reason: string };
}
export interface RunEvent { type: 'start' | 'scout' | 'stage' | 'trace' | 'result' | 'ping'; t: number; [k: string]: any; }
export interface AgentResult { status: string; summary: string; verdict: any; plan: { tool: string; args?: any; why?: string }[]; rounds: number; retrieved?: number; }
export interface RunSummary { run_id: string; at: string; prompt: string; mrn: string; user: { id: string; role: string }; ai: boolean; mode: string; status: string; steps: number; }

export function errorText(e: unknown): string {
  if (e instanceof HttpErrorResponse) {
    const body = e.error as { error?: string } | string | null;
    if (body && typeof body === 'object' && body.error) return body.error;
    if (e.status === 0) return 'The ClinAssist backend is not reachable. Start it with: python -m server';
    return `${e.status} ${e.statusText}`;
  }
  return e instanceof Error ? e.message : String(e);
}

@Injectable({ providedIn: 'root' })
export class Api {
  private http = inject(HttpClient);

  private get<T>(url: string): Promise<T> { return firstValueFrom(this.http.get<T>(url)); }
  private post<T>(url: string, body: unknown): Promise<T> { return firstValueFrom(this.http.post<T>(url, body)); }

  status(fresh = false) { return this.get<Status>(`/api/status${fresh ? '?fresh=1' : ''}`); }
  setMode(mode: 'zetaris' | 'csv') { return this.post<{ mode: string }>('/api/settings', { mode }); }
  sources(fresh = false) { return this.get<SourceCounts>(`/api/sources${fresh ? '?fresh=1' : ''}`); }
  query(sql: string) { return this.post<QueryResult>('/api/query', { sql }); }
  patients() { return this.get<PatientListItem[]>('/api/patients'); }
  patient(mrn: string, fresh = false) { return this.get<PatientReview>(`/api/patients/${encodeURIComponent(mrn)}${fresh ? '?fresh=1' : ''}`); }
  evidence(mrn: string, eid: string) { return this.get<EvidenceItem>(`/api/patients/${encodeURIComponent(mrn)}/evidence/${encodeURIComponent(eid)}`); }
  systemsView(mrn: string) { return this.get<SystemsView>(`/api/patients/${encodeURIComponent(mrn)}/systems`); }
  provenance(mrn: string) { return this.get<{ mrn: string; entity_id: string; events: ProvenanceEvent[] }>(`/api/patients/${encodeURIComponent(mrn)}/provenance`); }
  identity() { return this.get<IdentityView>('/api/identity'); }
  review(body: { system: string; record_id: string; action: 'approve' | 'reject'; by: string; note?: string }) { return this.post<any>('/api/identity/review', body); }
  rematch(by: string) { return this.post<any>('/api/identity/rematch', { by }); }
  meterlessRuns() { return this.get<{ runs: string[] }>('/api/meterless/runs'); }
  meterlessRun(id: string) { return this.get<{ run_id: string; events: any[]; audit: any[] }>(`/api/meterless/runs/${encodeURIComponent(id)}`); }
  scout(body: { prompt: string; mrn: string; role: string; user?: string }) { return this.post<ScoutDecision>('/api/scout', body); }
  runs() { return this.get<RunSummary[]>('/api/runs'); }
  run(id: string) { return this.get<any>(`/api/runs/${encodeURIComponent(id)}`); }
  evaluation() { return this.get<any>('/api/evaluation'); }

  /** Streams one agent run (Server-Sent Events over a POST). Calls onEvent for every step as it happens. */
  async runAgent(body: { prompt: string; mrn: string; role: string; user?: string; ai: boolean }, onEvent: (e: RunEvent) => void,
                 signal?: AbortSignal): Promise<void> {
    const res = await fetch('/api/agent/run', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal });
    if (!res.ok || !res.body) {
      let msg = `${res.status} ${res.statusText}`;
      try { msg = (await res.json()).error ?? msg; } catch { /* not JSON */ }
      throw new Error(msg);
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i: number;
      while ((i = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, i);
        buf = buf.slice(i + 2);
        const line = chunk.split('\n').find((l) => l.startsWith('data:'));
        if (line) {
          const ev = JSON.parse(line.slice(5).trim()) as RunEvent;
          if (ev.type !== 'ping') onEvent(ev);
        }
      }
    }
  }
}
