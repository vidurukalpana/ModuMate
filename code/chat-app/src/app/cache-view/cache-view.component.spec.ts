import { ComponentFixture, TestBed, discardPeriodicTasks, fakeAsync, tick } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { CacheViewComponent } from './cache-view.component';
import { environment } from '../../environments/environment';

describe('CacheViewComponent', () => {
  let fixture: ComponentFixture<CacheViewComponent>;
  let http: HttpTestingController;
  const api = environment.apiBaseUrl;
  const stats = {
    capacity: 4, entries: 4, hits: 3, exact_hits: 2, semantic_hits: 1, misses: 5,
    hit_rate: 0.375, evictions: 1, semantic_threshold: 0.75, ttl_seconds: null
  };

  const text = (selector: string) =>
    Array.from((fixture.nativeElement as HTMLElement).querySelectorAll(selector))
      .map((el) => el.textContent?.trim());

  beforeEach(() => {
    try {
      sessionStorage.removeItem('modumate-cache-token');
    } catch {
      // Ignore unavailable storage.
    }
    TestBed.configureTestingModule({
      imports: [CacheViewComponent],
      providers: [provideHttpClient(), provideHttpClientTesting()]
    });
    fixture = TestBed.createComponent(CacheViewComponent);
    http = TestBed.inject(HttpTestingController);
  });

  it('shows statistics without a token and asks for one to show slots', fakeAsync(() => {
    fixture.detectChanges();
    tick();
    http.expectOne(`${api}/cache/stats`).flush(stats);
    http.expectNone(`${api}/cache/rows`);
    fixture.detectChanges();

    expect(text('.stat .value')).toEqual(['4 / 4', '2', '1', '5', '38%', '1']);
    expect(text('.token label')).toEqual(['Admin token to show the cached questions']);
    fixture.destroy();
    discardPeriodicTasks();
  }));

  it('lists every slot and marks the first lowest-count row as replaced next', fakeAsync(() => {
    fixture.componentInstance.token = 'demo';
    fixture.detectChanges();
    tick();
    http.expectOne(`${api}/cache/stats`).flush(stats);
    const rows = http.expectOne(`${api}/cache/rows`);
    expect(rows.request.headers.get('Authorization')).toBe('Bearer demo');
    rows.flush({ rows: [
      { row: 0, question: 'What does MIMD stand for?', access_count: 2 },
      { row: 1, question: 'What is NUMA?', access_count: 0 },
      { row: 2, question: 'Explain bus snooping', access_count: 1 },
      { row: 3, question: 'What is CC-NUMA?', access_count: 0 }
    ] });
    fixture.detectChanges();

    expect(text('.slot .question')).toEqual([
      'What does MIMD stand for?', 'What is NUMA?', 'Explain bus snooping', 'What is CC-NUMA?'
    ]);
    expect(text('.slot.victim .question')).toEqual(['What is NUMA?']);
    expect(text('.slot .count')).toEqual(['Used 2 times', 'Used 0 times', 'Used 1 time', 'Used 0 times']);
    fixture.destroy();
    discardPeriodicTasks();
  }));

  it('shows empty slots up to capacity', fakeAsync(() => {
    fixture.componentInstance.token = 'demo';
    fixture.detectChanges();
    tick();
    http.expectOne(`${api}/cache/stats`).flush({ ...stats, entries: 1 });
    http.expectOne(`${api}/cache/rows`).flush({ rows: [{ row: 0, question: 'q', access_count: 0 }] });
    fixture.detectChanges();

    expect(text('.slot.empty').length).toBe(3);
    expect(text('.slot.victim').length).toBe(0);
    fixture.destroy();
    discardPeriodicTasks();
  }));
});
