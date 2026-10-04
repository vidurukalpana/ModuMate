import { ChangeDetectionStrategy, Component, EventEmitter, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { FormsModule } from '@angular/forms';
import { Subscription, catchError, forkJoin, of, switchMap, timer } from 'rxjs';

import { environment } from '../../environments/environment';

export interface CacheStats {
  capacity: number;
  entries: number;
  hits: number;
  exact_hits: number;
  semantic_hits: number;
  misses: number;
  hit_rate: number;
  evictions: number;
  semantic_threshold: number;
  ttl_seconds: number | null;
}

export interface CacheRow {
  row: number;
  question: string;
  access_count: number;
}

export type Slot = { row: number; entry: CacheRow | null; nextToReplace: boolean };

const REFRESH_MS = 2000;
const TOKEN_KEY = 'modumate-cache-token';

/** Live view of the backend answer cache: a side panel on the chat page, or its own page at /cache. */
@Component({
  selector: 'app-cache-view',
  templateUrl: './cache-view.component.html',
  styleUrls: ['./cache-view.component.css'],
  changeDetection: ChangeDetectionStrategy.Eager,
  imports: [FormsModule],
  host: { '[class.embedded]': 'embedded' }
})
export class CacheViewComponent implements OnInit, OnDestroy {
  /** Compact layout with a close button, for the panel beside the chat. */
  @Input() embedded = false;
  @Output() closed = new EventEmitter<void>();

  stats: CacheStats | null = null;
  rows: CacheRow[] | null = null;
  // Typed in by the presenter and kept only in this tab; never part of the app bundle.
  token = readToken();
  statsError = '';
  rowsError = '';
  clearMessage = '';
  private polling?: Subscription;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.polling = timer(0, REFRESH_MS).pipe(switchMap(() => this.load())).subscribe();
  }

  ngOnDestroy(): void {
    this.polling?.unsubscribe();
  }

  /** Every slot up to capacity, marking the row a new answer would replace when full. */
  get slots(): Slot[] {
    const capacity = this.stats?.capacity ?? 0;
    const rows = this.rows ?? [];
    const full = rows.length >= capacity && capacity > 0;
    const lowest = Math.min(...rows.map((r) => r.access_count));
    const victim = full ? rows.find((r) => r.access_count === lowest)?.row : undefined;
    return Array.from({ length: capacity }, (_, row) => {
      const entry = rows.find((r) => r.row === row) ?? null;
      return { row, entry, nextToReplace: entry !== null && entry.row === victim };
    });
  }

  saveToken(): void {
    try {
      sessionStorage.setItem(TOKEN_KEY, this.token);
    } catch {
      // Storage can be unavailable; the token still works for this page view.
    }
    this.refresh();
  }

  refresh(): void {
    this.load().subscribe();
  }

  clearCache(): void {
    this.http.post<{ removed: number }>(`${environment.apiBaseUrl}/cache/clear`, null, { headers: this.auth() })
      .subscribe({
        next: ({ removed }) => {
          this.clearMessage = `Cleared ${removed} ${removed === 1 ? 'entry' : 'entries'}.`;
          this.refresh();
        },
        error: (error: HttpErrorResponse) => (this.clearMessage = describe(error))
      });
  }

  private load() {
    const stats$ = this.http.get<CacheStats>(`${environment.apiBaseUrl}/cache/stats`).pipe(
      catchError((error: HttpErrorResponse) => {
        this.statsError = describe(error);
        return of(null);
      })
    );
    const rows$ = this.token.trim()
      ? this.http.get<{ rows: CacheRow[] }>(`${environment.apiBaseUrl}/cache/rows`, { headers: this.auth() }).pipe(
          catchError((error: HttpErrorResponse) => {
            this.rowsError = describe(error);
            return of(null);
          })
        )
      : of(null);
    return forkJoin([stats$, rows$]).pipe(
      switchMap(([stats, rows]) => {
        if (stats) {
          this.stats = stats;
          this.statsError = '';
        }
        if (rows) {
          this.rows = rows.rows;
          this.rowsError = '';
        } else if (!this.token.trim()) {
          this.rows = null;
          this.rowsError = '';
        }
        return of(null);
      })
    );
  }

  private auth(): HttpHeaders {
    return new HttpHeaders({ Authorization: `Bearer ${this.token.trim()}` });
  }
}

function readToken(): string {
  try {
    return sessionStorage.getItem(TOKEN_KEY) ?? '';
  } catch {
    return '';
  }
}

function describe(error: HttpErrorResponse): string {
  if (error.status === 0) {
    return 'Cannot reach the backend. Check that it is running.';
  }
  if (error.status === 401) {
    return 'Wrong admin token.';
  }
  if (error.status === 403) {
    return 'Cache admin is disabled. Set CACHE_ADMIN_TOKEN in the backend .env and restart it.';
  }
  return 'The backend returned an error.';
}
