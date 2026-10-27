import { ApplicationConfig, provideZonelessChangeDetection } from '@angular/core';
import { provideHttpClient, withFetch } from '@angular/common/http';
import { RouteReuseStrategy, provideRouter, withComponentInputBinding } from '@angular/router';
import { KeepAliveStrategy } from './core/keep-alive';
import { routes } from './app.routes';

export const appConfig: ApplicationConfig = {
  providers: [
    provideZonelessChangeDetection(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withFetch()),
    { provide: RouteReuseStrategy, useClass: KeepAliveStrategy },
  ],
};
