import { Injectable } from '@angular/core';
import { ActivatedRouteSnapshot, DetachedRouteHandle, RouteReuseStrategy } from '@angular/router';

/**
 * Keeps every page alive when you move to another page, so a page comes back exactly as you left it
 * (chat thread, selected record, query results, opened panels). Pages are stored by their path.
 */
@Injectable()
export class KeepAliveStrategy implements RouteReuseStrategy {
  private stored = new Map<string, DetachedRouteHandle>();

  private key(route: ActivatedRouteSnapshot): string | null {
    return route.routeConfig?.path && route.routeConfig.path !== '**' ? route.routeConfig.path : null;
  }
  shouldDetach(route: ActivatedRouteSnapshot): boolean { return !!this.key(route) && !!route.routeConfig?.loadComponent; }
  store(route: ActivatedRouteSnapshot, handle: DetachedRouteHandle | null): void {
    const k = this.key(route);
    if (!k) return;
    if (handle) this.stored.set(k, handle); else this.stored.delete(k);
  }
  shouldAttach(route: ActivatedRouteSnapshot): boolean { const k = this.key(route); return !!k && this.stored.has(k); }
  retrieve(route: ActivatedRouteSnapshot): DetachedRouteHandle | null { const k = this.key(route); return k ? this.stored.get(k) ?? null : null; }
  shouldReuseRoute(future: ActivatedRouteSnapshot, curr: ActivatedRouteSnapshot): boolean { return future.routeConfig === curr.routeConfig; }
}
