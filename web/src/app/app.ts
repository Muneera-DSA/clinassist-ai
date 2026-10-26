import { Component, OnInit, computed, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { Api } from './core/api';
import { AppState } from './core/state';
import { EvidenceDrawer } from './ui/components';

interface NavItem { path: string; label: string; hint: string; icon: string; }

@Component({
  selector: 'ca-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, EvidenceDrawer],
  template: `
    <div class="shell">
      <nav class="side">
        <div class="brand">
          <div class="logo">+</div>
          <div><div class="name">ClinAssist AI</div><div class="tag">Longitudinal clinical intelligence</div></div>
        </div>
        <div class="nav">
          @for (n of nav; track n.path; let i = $index) {
            <a [routerLink]="n.path" routerLinkActive="active" class="nav-item">
              <span class="step">{{ i + 1 }}</span>
              <span class="txt"><span class="lbl">{{ n.label }}</span><span class="hint">{{ n.hint }}</span></span>
            </a>
          }
        </div>
        <div class="side-foot">
          <div class="mode">
            <span class="dot" [class.ok]="liveOk()" [class.warn]="state.status()?.mode === 'csv'" [class.bad]="state.status()?.mode === 'zetaris' && !liveOk()"></span>
            <span>{{ modeLabel() }}</span>
          </div>
          <button class="btn sm ghost toggle" (click)="toggleMode()" title="Switch between live Zetaris and the offline CSV copy">
            Switch to {{ state.status()?.mode === 'csv' ? 'Zetaris (live)' : 'offline copy' }}
          </button>
          <div class="fine">Synthetic data only · NexAgent team</div>
        </div>
      </nav>
      <main class="main">
        @if (state.statusError()) { <div class="notice bad banner">{{ state.statusError() }}</div> }
        @else if (state.status()?.mode === 'csv') {
          <div class="notice warn banner">Offline copy: patient data is read from the local CSV files, not through Zetaris. Switch to live for the demo.</div>
        }
        <router-outlet />
      </main>
    </div>
    <ca-evidence-drawer />
  `,
  styles: [`
    .shell { display: grid; grid-template-columns: 248px 1fr; min-height: 100vh; }
    .side { background: var(--shell); color: var(--shell-text); display: flex; flex-direction: column; position: sticky; top: 0; height: 100vh; }
    .brand { display: flex; gap: 10px; align-items: center; padding: 18px 16px 14px; border-bottom: 1px solid rgba(255,255,255,.06); }
    .logo { width: 34px; height: 34px; border-radius: 9px; background: var(--primary); color: #fff; font-weight: 800; font-size: 22px; display: grid; place-items: center; }
    .name { color: #fff; font-weight: 700; font-size: 15px; }
    .tag { font-size: 11px; color: #8ea0b8; }
    .nav { padding: 10px 8px; display: flex; flex-direction: column; gap: 2px; flex: 1; overflow: auto; }
    .nav-item { display: flex; gap: 10px; align-items: flex-start; padding: 9px 10px; border-radius: 8px; color: var(--shell-text); text-decoration: none; }
    .nav-item:hover { background: var(--shell-2); text-decoration: none; }
    .nav-item.active { background: #1d3150; color: #fff; }
    .nav-item.active .step { background: var(--primary); color: #fff; border-color: var(--primary); }
    .step { width: 22px; height: 22px; flex: none; border-radius: 50%; border: 1px solid #37506f; display: grid; place-items: center; font-size: 11px; font-weight: 700; margin-top: 1px; }
    .txt { display: flex; flex-direction: column; }
    .lbl { font-weight: 600; font-size: 13.5px; }
    .hint { font-size: 11.5px; color: #8ea0b8; }
    .side-foot { padding: 12px 16px 16px; border-top: 1px solid rgba(255,255,255,.06); display: flex; flex-direction: column; gap: 6px; }
    .mode { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #dbe5f2; }
    .toggle { color: #9fb3cc; justify-content: flex-start; padding-left: 0; }
    .toggle:hover { background: transparent; color: #fff; }
    .fine { font-size: 11px; color: #6f839e; }
    .main { min-width: 0; }
    .banner { margin: 12px 28px 0; }
    @media (max-width: 900px) { .shell { grid-template-columns: 1fr; } .side { position: static; height: auto; } }
  `],
})
export class App implements OnInit {
  readonly state = inject(AppState);
  private api = inject(Api);
  readonly nav: NavItem[] = [
    { path: '/overview', label: 'Overview', hint: 'The problem and the live system', icon: '' },
    { path: '/sources', label: 'Fragmented data', hint: 'SQL Server · MySQL · PostgreSQL via Zetaris', icon: '' },
    { path: '/identity', label: 'Identity resolution', hint: 'Matcher + Meterless World Model', icon: '' },
    { path: '/patient', label: 'Patient review', hint: '3-year evidence-linked analysis', icon: '' },
    { path: '/ask', label: 'Ask ClinAssist', hint: 'Scout → agent loop → verifier', icon: '' },
    { path: '/evaluation', label: 'Evaluation', hint: 'How we tested it', icon: '' },
    { path: '/audit', label: 'Audit trail', hint: 'Every run, step by step', icon: '' },
  ];
  readonly liveOk = computed(() => this.state.status()?.mode === 'zetaris' && !!this.state.status()?.zetaris.ok);
  readonly modeLabel = computed(() => {
    const s = this.state.status();
    if (!s) return 'Connecting…';
    if (s.mode === 'csv') return 'Data path: offline CSV copy';
    return s.zetaris.ok ? `Data path: Zetaris (live, ${s.zetaris.seconds}s)` : 'Zetaris not reachable';
  });

  ngOnInit(): void { this.state.start(); }

  async toggleMode(): Promise<void> {
    const next = this.state.status()?.mode === 'csv' ? 'zetaris' : 'csv';
    await this.api.setMode(next);
    await this.state.refreshStatus(true);
    await this.state.refreshPatients();
  }
}
