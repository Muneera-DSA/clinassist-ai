import { Injectable, computed, inject, signal } from '@angular/core';
import { Api, PatientListItem, Status, errorText } from './api';

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
