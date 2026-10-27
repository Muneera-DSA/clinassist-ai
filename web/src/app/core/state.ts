import { Injectable, computed, inject, signal } from '@angular/core';
import { Api, PatientListItem, Status, errorText } from './api';

/** Who is using ClinAssist. Chosen on first open; decides which pages appear and the role sent with every request. */
export type Persona = 'doctor' | 'staff' | 'insurance';
export interface PersonaInfo { key: Persona; label: string; role: string; user: string; blurb: string; pages: string[]; }
/** Every page, in demo order: what Judge view shows, in any role. */
export const ALL_PAGES = ['/overview', '/sources', '/identity', '/patient', '/prescriptions', '/ask', '/evaluation', '/audit'];
export const PERSONAS: PersonaInfo[] = [
  { key: 'doctor', label: 'Doctor', role: 'clinician', user: 'dr.demo', blurb: 'Review a patient\'s 3-year history, medicine safety and ask questions with cited answers.',
    pages: ['/patient', '/prescriptions', '/ask'] },
  { key: 'staff', label: 'Authorised hospital staff', role: 'records_staff', user: 'staff.demo', blurb: 'Confirm which hospital, lab and pharmacy records belong to the same person, and look up a patient\'s details and visits (no clinical results).',
    pages: ['/identity', '/ask'] },
  { key: 'insurance', label: 'Insurance coordinator', role: 'coordinator', user: 'coordinator.demo', blurb: 'Gather the documented evidence, findings and missing tests behind an authorization.',
    pages: ['/patient', '/ask'] },
];

/** App-wide state shared by every page: live status, the patient in focus and the evidence drawer. */
@Injectable({ providedIn: 'root' })
export class AppState {
  private api = inject(Api);

  readonly status = signal<Status | null>(null);
  readonly statusError = signal<string | null>(null);
  readonly patients = signal<PatientListItem[]>([]);
  /** The patient the demo is about. Kendrick (MRN91862E3E) has the richest 3-year history. */
  readonly mrn = signal<string>(localStorageGet('ca.mrn') ?? 'MRN91862E3E');
  readonly patient = computed(() => this.patients().find((p) => p.mrn === this.mrn()) ?? null);
  /** The person's chosen view (null until chosen). */
  readonly persona = signal<Persona | null>(PERSONAS.some((p) => p.key === localStorageGet('ca.persona')) ? localStorageGet('ca.persona') as Persona : null);
  /** Judge view: every page and the technical panels, in any role. Chat permissions still follow the role. */
  readonly judge = signal<boolean>(localStorageGet('ca.judge') === '1');
  setJudge(on: boolean): void { this.judge.set(on); localStorageSet('ca.judge', on ? '1' : '0'); }
  readonly personaInfo = computed(() => PERSONAS.find((p) => p.key === this.persona()) ?? null);
  /** The role sent to Scout and Meterless with every request. */
  readonly apiRole = computed(() => this.personaInfo()?.role ?? 'clinician');
  readonly apiUser = computed(() => this.personaInfo()?.user ?? 'demo.user');
  canSee(path: string): boolean { const p = this.personaInfo(); return this.judge() || !p || p.pages.includes(path); }
  home(): string { return this.judge() ? '/overview' : this.personaInfo()?.pages[0] ?? '/overview'; }
  setPersona(p: Persona | null): void {
    this.persona.set(p);
    if (p) localStorageSet('ca.persona', p); else { try { localStorage.removeItem('ca.persona'); } catch { /* private mode */ } }
  }
  /** Evidence drawer: which evidence id is open, for which patient. */
  readonly evidence = signal<{ mrn: string; eid: string } | null>(null);

  private timer: ReturnType<typeof setInterval> | null = null;

  start(): void {
    this.refreshStatus();
    this.refreshPatients();
    this.timer ??= setInterval(() => this.refreshStatus(), 30000);
  }

  async refreshStatus(fresh = false): Promise<void> {
    try {
      this.status.set(await this.api.status(fresh));
      this.statusError.set(null);
    } catch (e) {
      this.statusError.set(errorText(e));
    }
  }

  async refreshPatients(): Promise<void> {
    try { this.patients.set(await this.api.patients()); } catch { /* status banner explains */ }
  }

  selectPatient(mrn: string): void {
    this.mrn.set(mrn);
    localStorageSet('ca.mrn', mrn);
  }

  openEvidence(eid: string, mrn = this.mrn()): void { this.evidence.set({ mrn, eid }); }
  closeEvidence(): void { this.evidence.set(null); }
}

function localStorageGet(k: string): string | null {
  try { return localStorage.getItem(k); } catch { return null; }
}
function localStorageSet(k: string, v: string): void {
  try { localStorage.setItem(k, v); } catch { /* private mode */ }
}

export const ENGINE_CLASS: Record<string, string> = { hospital_ehr: 'mssql', lab_lis: 'mysql', pharmacy_rx: 'pg' };
export const SYSTEM_OF_LINK: Record<string, string> = { laboratory: 'lab_lis', pharmacy: 'pharmacy_rx', hospital: 'hospital_ehr' };
export const SYSTEM_LABEL: Record<string, string> = { hospital_ehr: 'Hospital EHR', lab_lis: 'Laboratory LIS', pharmacy_rx: 'Pharmacy' };
export const ENGINE_SHORT: Record<string, string> = { hospital_ehr: 'SQL Server', lab_lis: 'MySQL', pharmacy_rx: 'PostgreSQL' };
