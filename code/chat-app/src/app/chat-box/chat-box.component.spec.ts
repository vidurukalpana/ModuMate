import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { Subject, throwError } from 'rxjs';

import { ChatBoxComponent } from './chat-box.component';
import { ChatServiceService } from '../chat-service.service';
import { Answer } from '../models/Answer';

describe('ChatBoxComponent', () => {
  let fixture: ComponentFixture<ChatBoxComponent>;
  let component: ChatBoxComponent;
  let chatService: jasmine.SpyObj<ChatServiceService>;

  const text = (selector: string) =>
    Array.from((fixture.nativeElement as HTMLElement).querySelectorAll(selector))
      .map((el) => el.textContent?.trim());

  beforeEach(() => {
    chatService = jasmine.createSpyObj('ChatServiceService', ['getAnswer']);
    TestBed.configureTestingModule({
      imports: [FormsModule],
      declarations: [ChatBoxComponent],
      providers: [{ provide: ChatServiceService, useValue: chatService }]
    });
    fixture = TestBed.createComponent(ChatBoxComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('clears the input and blocks duplicate sends while waiting', () => {
    const response = new Subject<Answer>();
    chatService.getAnswer.and.returnValue(response);

    component.newMessage = '  What is UMA?  ';
    component.sendMessage();
    component.newMessage = 'second';
    component.sendMessage();
    fixture.detectChanges();

    expect(chatService.getAnswer).toHaveBeenCalledOnceWith('What is UMA?');
    expect(component.newMessage).toBe('second');
    expect(text('.thinking')).toEqual(['Thinking…']);

    response.next({
      answer: 'Uniform memory access.',
      source: 'local_qa',
      cache_hit: false,
      sources: [{ id: '1', source: 'UMA.txt', topic: 'UMA', chunk_index: 0, excerpt: 'UMA excerpt' }]
    });
    fixture.detectChanges();

    expect(component.pending).toBeFalse();
    expect(text('.message .text')).toEqual(['What is UMA?', 'Uniform memory access.']);
    expect(text('.origin')).toEqual(['Extracted from course notes']);
    expect(text('.cache')).toEqual([]);
    expect(text('summary')).toEqual(['Sources (1)']);
  });

  it('labels cached AI answers and shows the semantic match', () => {
    const response = new Subject<Answer>();
    chatService.getAnswer.and.returnValue(response);
    component.newMessage = 'Explain cache coherence.';
    component.sendMessage();
    response.next({
      answer: 'Caches keep shared data consistent.',
      source: 'llm_fallback',
      cache_hit: true,
      cache_match_type: 'semantic',
      cache_similarity: 0.912,
      cache_matched_question: 'What is cache coherence?',
      sources: []
    });
    fixture.detectChanges();

    expect(text('.origin')).toEqual(['Cached answer']);
    expect(text('.cache')).toEqual(['Similar to “What is cache coherence?” (0.91)']);
  });

  it('toggles the cache panel from the header', () => {
    const toggled = jasmine.createSpy('cacheToggle');
    component.cacheToggle.subscribe(toggled);
    const button = (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.header-actions .clear')!;
    expect(button.textContent?.trim()).toBe('Show cache');

    button.click();
    expect(toggled).toHaveBeenCalledTimes(1);

    component.cacheOpen = true;
    fixture.detectChanges();
    expect(button.textContent?.trim()).toBe('Hide cache');
    expect(button.getAttribute('aria-pressed')).toBe('true');
  });

  it('ignores blank input', () => {
    component.newMessage = '   ';
    component.sendMessage();
    expect(chatService.getAnswer).not.toHaveBeenCalled();
  });

  it('shows errors in the conversation', () => {
    chatService.getAnswer.and.returnValue(throwError(() => new Error('Server down')));
    component.newMessage = 'q';
    component.sendMessage();
    fixture.detectChanges();

    expect(component.pending).toBeFalse();
    expect(text('.error .text')).toEqual(['Server down']);
  });

  it('fills in a starter question without sending it', () => {
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.starter')!.click();
    expect(component.newMessage).toBe('Explain ');
    expect(chatService.getAnswer).not.toHaveBeenCalled();
  });

  it('offers suggested topics as follow-up questions', () => {
    const first = new Subject<Answer>();
    chatService.getAnswer.and.returnValue(first);
    component.newMessage = 'weather?';
    component.sendMessage();
    first.next({
      answer: 'Not covered.',
      source: 'question_policy',
      cache_hit: false,
      sources: [],
      suggested_topics: ['Cache coherence']
    });
    fixture.detectChanges();

    chatService.getAnswer.and.returnValue(new Subject<Answer>());
    (fixture.nativeElement as HTMLElement).querySelector<HTMLButtonElement>('.topics button')!.click();
    expect(chatService.getAnswer).toHaveBeenCalledWith('Explain Cache coherence.');
  });
});
