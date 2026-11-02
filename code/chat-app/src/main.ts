import 'zone.js';

import { provideZoneChangeDetection } from '@angular/core';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { bootstrapApplication } from '@angular/platform-browser';
import { platformBrowserDynamic } from '@angular/platform-browser-dynamic';

import { AppModule } from './app/app.module';
import { CacheViewComponent } from './app/cache-view/cache-view.component';


// /cache is a separate page that leaves the chat app untouched.
if (location.pathname.replace(/\/+$/, '') === '/cache') {
  document.title = 'ModuMate · Answer cache';
  document.querySelector('app-root')?.replaceWith(document.createElement('app-cache-view'));
  bootstrapApplication(CacheViewComponent, {
    providers: [provideZoneChangeDetection(), provideHttpClient(withXhr())]
  }).catch(err => console.error(err));
} else {
  platformBrowserDynamic().bootstrapModule(AppModule, { applicationProviders: [provideZoneChangeDetection()] })
    .catch(err => console.error(err));
}
