import { NO_ERRORS_SCHEMA } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AppComponent } from './app.component';

describe('AppComponent', () => {
  beforeEach(() => {
    try {
      localStorage.removeItem('modumate-cache-panel');
    } catch {
      // Ignore unavailable storage.
    }
    TestBed.configureTestingModule({
      declarations: [AppComponent],
      schemas: [NO_ERRORS_SCHEMA]
    });
  });

  it('renders the heading and chat box', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('h1')?.textContent).toContain('ModuMate');
    expect(compiled.querySelector('app-chat-box')).toBeTruthy();
  });

  it('shows the cache panel beside the chat and removes it when closed', () => {
    const fixture = TestBed.createComponent(AppComponent);
    fixture.detectChanges();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('.workspace.with-cache app-cache-view')).toBeTruthy();

    fixture.componentInstance.toggleCache();
    fixture.detectChanges();
    expect(compiled.querySelector('app-cache-view')).toBeNull();
    expect(compiled.querySelector('.workspace.with-cache')).toBeNull();

    // The choice is remembered for the next visit.
    expect(TestBed.createComponent(AppComponent).componentInstance.cacheOpen).toBeFalse();
  });
});
