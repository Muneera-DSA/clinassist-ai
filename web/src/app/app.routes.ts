import { inject } from '@angular/core';
import { CanActivateFn, Router, Routes } from '@angular/router';
import { AppState } from './core/state';

/** Pages follow the chosen role: a page outside it sends the person to their own first page. */
const forRole: CanActivateFn = (route) => {
  const state = inject(AppState);
  const path = '/' + (route.routeConfig?.path ?? '');
  return state.canSee(path) ? true : inject(Router).parseUrl(state.home());
};

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'overview' },
  { path: 'overview', canActivate: [forRole], loadComponent: () => import('./pages/overview').then((m) => m.OverviewPage), title: 'Overview · ClinAssist AI' },
  { path: 'sources', canActivate: [forRole], loadComponent: () => import('./pages/sources').then((m) => m.SourcesPage), title: 'Data sources · ClinAssist AI' },
  { path: 'identity', canActivate: [forRole], loadComponent: () => import('./pages/identity').then((m) => m.IdentityPage), title: 'Identity · ClinAssist AI' },
  { path: 'patient', canActivate: [forRole], loadComponent: () => import('./pages/patient').then((m) => m.PatientPage), title: 'Patient review · ClinAssist AI' },
  { path: 'prescriptions', canActivate: [forRole], loadComponent: () => import('./pages/prescriptions').then((m) => m.PrescriptionsPage), title: 'Medicine review · ClinAssist AI' },
  { path: 'ask', canActivate: [forRole], loadComponent: () => import('./pages/ask').then((m) => m.AskPage), title: 'Ask ClinAssist · ClinAssist AI' },
  { path: 'evaluation', canActivate: [forRole], loadComponent: () => import('./pages/evaluation').then((m) => m.EvaluationPage), title: 'Evaluation · ClinAssist AI' },
  { path: 'audit', canActivate: [forRole], loadComponent: () => import('./pages/audit').then((m) => m.AuditPage), title: 'Audit trail · ClinAssist AI' },
  { path: '**', redirectTo: 'overview' },
];
