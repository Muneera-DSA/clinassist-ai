import { Component, OnInit, computed, effect, inject } from '@angular/core';
import { NavigationEnd, Router, RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { toSignal } from '@angular/core/rxjs-interop';
import { filter, map } from 'rxjs';
import { AppState, PERSONAS, Persona } from './core/state';
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
          @for (n of shownNav(); track n.path; let i = $index) {
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
          @if (state.personaInfo(); as p) {
            <div class="who"><span class="small">Signed in as <b>{{ p.label }}</b></span>
              <button class="btn sm ghost switch" (click)="state.setPersona(null)">Change role</button></div>
            <label class="judge-sw" title="Show every page and the technical panels. Chat permissions still follow your role.">
              <input type="checkbox" [checked]="state.judge()" (change)="setJudge($any($event.target).checked)" />
              <span class="track"><span class="knob"></span></span>
              <span>Judge view <span class="jhint">{{ state.judge() ? 'all pages shown' : 'show everything' }}</span></span>
            </label>
          }
          <div class="fine">Synthetic data only · NexAgent team</div>
        </div>
      </nav>
      <main class="main">
        @if (state.statusError()) { <div class="notice bad banner">{{ state.statusError() }}</div> }
        <router-outlet />
      </main>
    </div>
    <ca-evidence-drawer />
    @if (!state.persona()) {
      <div class="picker">
        <div class="picker-card">
          <div class="brand-row"><div class="logo">+</div><div><div class="pname">ClinAssist AI</div><div class="ptag">Longitudinal clinical intelligence</div></div></div>
          <h1>Who are you?</h1>
          <p class="muted">ClinAssist shows each person only what their work needs. Your role is also sent with every request, and Scout and
            Meterless enforce it: a role cannot run what it is not allowed to.</p>
          <div class="pgrid">
            @for (p of personas; track p.key) {
              <button class="pcard" (click)="choose(p.key)">
                <div class="pt">{{ p.label }}</div>
                <div class="pb">{{ p.blurb }}</div>
                <div class="pp">{{ pagesOf(p.pages) }}</div>
              </button>
            }
          </div>
          <label class="judge-pick"><input type="checkbox" [checked]="state.judge()" (change)="state.setJudge($any($event.target).checked)" />
            <span><b>Judge view</b>: also show every page, the architecture, the Scout safety tests and the evaluation. Chat permissions still
              follow the role you pick, so you can see exactly what each role is allowed to do.</span></label>
          <p class="small faint">Synthetic data only. You can change role or switch Judge view on or off at any time from the sidebar.</p>
        </div>
      </div>
    }
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
    .fine { font-size: 11px; color: #6f839e; }
    .who { display: flex; align-items: center; justify-content: space-between; gap: 6px; color: #dbe5f2; }
    .switch { color: #9fb3cc; padding: 2px 6px; }
    .switch:hover { background: transparent; color: #fff; }
    .picker { position: fixed; inset: 0; z-index: 100; background: rgba(13, 22, 38, .72); display: grid; place-items: center; padding: 24px; overflow: auto; }
    .picker-card { background: var(--surface); border-radius: 16px; padding: 28px 30px; width: min(980px, 100%); box-shadow: 0 30px 80px rgba(0,0,0,.35); }
    .picker-card h1 { margin: 18px 0 4px; font-size: 24px; }
    .brand-row { display: flex; gap: 10px; align-items: center; }
    .pname { font-weight: 800; font-size: 16px; } .ptag { font-size: 12px; color: var(--muted); }
    .pgrid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 18px 0 12px; }
    .pcard { text-align: left; border: 1px solid var(--line-strong); background: var(--surface); border-radius: 12px; padding: 16px 14px; cursor: pointer;
      display: flex; flex-direction: column; gap: 8px; font: inherit; color: inherit; transition: border-color .15s, transform .15s, box-shadow .15s; }
    .pcard:hover { border-color: var(--primary); transform: translateY(-2px); box-shadow: 0 10px 24px -14px rgba(16,24,40,.4); }
    .judge-pick { display: flex; gap: 10px; align-items: flex-start; padding: 12px 14px; border: 1px dashed var(--line-strong); border-radius: 10px;
      background: var(--surface-2); font-size: 13px; line-height: 1.45; margin: 4px 0 10px; cursor: pointer; }
    .judge-pick input { margin-top: 3px; }
    .judge-sw { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #dbe5f2; cursor: pointer; user-select: none; }
    .judge-sw input { position: absolute; opacity: 0; width: 0; height: 0; }
    .judge-sw .track { width: 30px; height: 17px; border-radius: 99px; background: #37506f; position: relative; flex: none; transition: background .15s; }
    .judge-sw .knob { position: absolute; top: 2px; left: 2px; width: 13px; height: 13px; border-radius: 50%; background: #fff; transition: left .15s; }
    .judge-sw input:checked + .track { background: var(--primary); }
    .judge-sw input:checked + .track .knob { left: 15px; }
    .judge-sw input:focus-visible + .track { outline: 2px solid #8ec5ff; outline-offset: 2px; }
    .jhint { display: block; font-size: 11px; color: #8ea0b8; }
    .pt { font-weight: 750; font-size: 15px; } .pb { font-size: 12.5px; color: var(--muted); line-height: 1.45; flex: 1; }
    .pp { font-size: 11px; color: var(--primary); font-weight: 600; }
    @media (max-width: 900px) { .pgrid { grid-template-columns: 1fr 1fr; } }
    .main { min-width: 0; }
    .banner { margin: 12px 28px 0; }
    @media (max-width: 900px) { .shell { grid-template-columns: 1fr; } .side { position: static; height: auto; } }
  `],
})
export class App implements OnInit {
  readonly state = inject(AppState);
  readonly nav: NavItem[] = [
    { path: '/overview', label: 'Overview', hint: 'The problem and the live system', icon: '' },
    { path: '/sources', label: 'Fragmented data', hint: 'SQL Server · MySQL · PostgreSQL via Zetaris', icon: '' },
    { path: '/identity', label: 'Identity resolution', hint: 'Matcher + Meterless World Model', icon: '' },
    { path: '/patient', label: 'Patient review', hint: '3-year evidence-linked analysis', icon: '' },
    { path: '/prescriptions', label: 'Medicine review', hint: 'History · safety flags · FDA labels', icon: '' },
    { path: '/ask', label: 'Ask ClinAssist', hint: 'Meterless supervises · Nemotron leads', icon: '' },
    { path: '/evaluation', label: 'Evaluation', hint: 'How we tested it', icon: '' },
    { path: '/audit', label: 'Audit trail', hint: 'Meterless World Model record', icon: '' },
  ];
  readonly personas = PERSONAS;
  private router = inject(Router);
  readonly shownNav = computed(() => this.nav.filter((n) => this.state.canSee(n.path)));
  pagesOf(paths: string[]): string { return paths.map((p) => this.nav.find((n) => n.path === p)?.label ?? p).join(' · '); }
  choose(p: Persona): void { this.state.setPersona(p); this.router.navigateByUrl(this.state.home()); }
  setJudge(on: boolean): void { this.state.setJudge(on); if (!on && !this.state.canSee(this.url())) this.router.navigateByUrl(this.state.home()); }
  private readonly url = toSignal(this.router.events.pipe(filter((e) => e instanceof NavigationEnd), map(() => this.router.url.split('?')[0])),
    { initialValue: '/' });
  constructor() {
    // If the role changes (or Judge view is switched off) while on a page outside it, go to the role's first page.
    effect(() => {
      const u = this.url();
      if (this.state.persona() && u !== '/' && !this.state.canSee(u)) this.router.navigateByUrl(this.state.home());
    });
  }
  readonly liveOk = computed(() => this.state.status()?.mode === 'zetaris' && !!this.state.status()?.zetaris.ok);
  readonly modeLabel = computed(() => {
    const s = this.state.status();
    if (!s) return 'Connecting…';
    if (s.mode === 'csv') return 'Data path: offline CSV copy';
    return s.zetaris.ok ? `Data path: Zetaris (live, ${s.zetaris.seconds}s)` : 'Zetaris not reachable';
  });

  ngOnInit(): void { this.state.start(); }
}
