import { fakeAsync, TestBed, tick } from '@angular/core/testing';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';

import { ChatServiceService } from './chat-service.service';
import { environment } from '../environments/environment';
import { Answer } from './models/Answer';
import { provideHttpClient, withInterceptorsFromDi, withXhr } from '@angular/common/http';

describe('ChatServiceService', () => {
  const url = `${environment.apiBaseUrl}/api`;
  let service: ChatServiceService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [], providers: [provideHttpClient(withXhr(), withInterceptorsFromDi()), provideHttpClientTesting()] });
    service = TestBed.inject(ChatServiceService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('posts the question with the MP category', () => {
    const answer: Answer = { answer: 'A', source: 'local_qa', sources: [], cache_hit: false };
    let received: Answer | undefined;
    service.getAnswer('What is NUMA?').subscribe((a) => received = a);

    const req = http.expectOne(url);
    expect(req.request.method).toBe('POST');
    expect(req.request.body).toEqual({ question: 'What is NUMA?', category: 'MP' });
    req.flush(answer);
    expect(received).toEqual(answer);
  });

  it('retries when the backend is busy', fakeAsync(() => {
    let received: Answer | undefined;
    service.getAnswer('q').subscribe((a) => received = a);

    http.expectOne(url).flush(
      { error: 'Backend is busy; retry later', code: 'backend_busy' },
      { status: 503, statusText: 'Service Unavailable', headers: { 'Retry-After': '1' } }
    );
    tick(1000);
    http.expectOne(url).flush({ answer: 'ok', source: 'local_qa', sources: [], cache_hit: false });
    expect(received?.answer).toBe('ok');
  }));

  it('does not retry other errors and reports a readable message', () => {
    let message = '';
    service.getAnswer('q').subscribe({ error: (e: Error) => message = e.message });

    http.expectOne(url).flush(
      { error: 'LLM fallback could not complete the request', code: 'timeout' },
      { status: 504, statusText: 'Gateway Timeout' }
    );
    expect(message).toContain('took too long');
  });

  it('reports an unreachable backend', () => {
    let message = '';
    service.getAnswer('q').subscribe({ error: (e: Error) => message = e.message });

    http.expectOne(url).error(new ProgressEvent('error'), { status: 0 });
    expect(message).toContain('Cannot reach');
  });

  it('shows backend validation messages', () => {
    let message = '';
    service.getAnswer('q').subscribe({ error: (e: Error) => message = e.message });

    http.expectOne(url).flush(
      { error: 'question must be a non-empty string' },
      { status: 400, statusText: 'Bad Request' }
    );
    expect(message).toBe('question must be a non-empty string');
  });
});
