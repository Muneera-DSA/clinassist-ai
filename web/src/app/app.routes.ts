import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'overview' },
  { path: 'overview', loadComponent: () => import('./pages/overview').then((m) => m.OverviewPage), title: 'Overview · ClinAssist AI' },
  { path: 'sources', loadComponent: () => import('./pages/sources').then((m) => m.SourcesPage), title: 'Data sources · ClinAssist AI' },
  { path: 'identity', loadComponent: () => import('./pages/identity').then((m) => m.IdentityPage), title: 'Identity · ClinAssist AI' },
  { path: 'patient', loadComponent: () => import('./pages/patient').then((m) => m.PatientPage), title: 'Patient review · ClinAssist AI' },
  { path: 'ask', loadComponent: () => import('./pages/ask').then((m) => m.AskPage), title: 'Ask ClinAssist · ClinAssist AI' },
  { path: 'evaluation', loadComponent: () => import('./pages/evaluation').then((m) => m.EvaluationPage), title: 'Evaluation · ClinAssist AI' },
  { path: 'audit', loadComponent: () => import('./pages/audit').then((m) => m.AuditPage), title: 'Audit trail · ClinAssist AI' },
  { path: '**', redirectTo: 'overview' },
];
