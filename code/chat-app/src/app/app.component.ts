import { Component, ChangeDetectionStrategy } from '@angular/core';

const CACHE_PANEL_KEY = 'modumate-cache-panel';

@Component({
    selector: 'app-root',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class AppComponent {
  // Open by default; the viewer's choice is remembered in this browser.
  cacheOpen = readCachePanel();

  toggleCache(): void {
    this.cacheOpen = !this.cacheOpen;
    try {
      localStorage.setItem(CACHE_PANEL_KEY, this.cacheOpen ? 'open' : 'closed');
    } catch {
      // Storage can be unavailable; the panel still toggles for this visit.
    }
  }
}

function readCachePanel(): boolean {
  try {
    return localStorage.getItem(CACHE_PANEL_KEY) !== 'closed';
  } catch {
    return true;
  }
}
