import { Injectable } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Observable, catchError, retry, throwError, timer } from 'rxjs';

import { environment } from '../environments/environment';
import { Answer } from './models/Answer';

export const MAX_QUESTION_LENGTH = 2000;
const BUSY_RETRIES = 2;

@Injectable({
  providedIn: 'root'
})
export class ChatServiceService {
  private readonly apiUrl = `${environment.apiBaseUrl}/api`;

  constructor(private http: HttpClient) {}

  getAnswer(question: string): Observable<Answer> {
    return this.http.post<Answer>(this.apiUrl, { question, category: 'MP' }).pipe(
      // The backend asks clients to retry after 1s when its request slots are full.
      retry({
        count: BUSY_RETRIES,
        delay: (error: HttpErrorResponse) => isBusy(error)
          ? timer(retryAfterMs(error))
          : throwError(() => error)
      }),
      catchError((error: HttpErrorResponse) => throwError(() => new Error(describeError(error))))
    );
  }
}

function isBusy(error: HttpErrorResponse): boolean {
  return error.status === 503 && error.error?.code === 'backend_busy';
}

function retryAfterMs(error: HttpErrorResponse): number {
  const seconds = Number(error.headers?.get('Retry-After'));
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 1000;
}

export function describeError(error: HttpErrorResponse): string {
  if (error.status === 0) {
    return 'Cannot reach the ModuMate server. Check that the backend is running.';
  }
  if (isBusy(error)) {
    return 'The server is busy right now. Please try again in a moment.';
  }
  if (error.status === 504) {
    return 'The answer took too long to generate. Please try again.';
  }
  if (error.status === 400 && typeof error.error?.error === 'string') {
    return error.error.error;
  }
  if (error.status === 413) {
    return 'That question is too long.';
  }
  if (error.status >= 500) {
    return 'The server could not answer right now. Please try again later.';
  }
  return 'Something went wrong while getting an answer.';
}
