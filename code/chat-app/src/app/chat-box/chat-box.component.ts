import { AfterViewChecked, Component, ElementRef, ViewChild, ChangeDetectionStrategy } from '@angular/core';

import { ChatServiceService, MAX_QUESTION_LENGTH } from '../chat-service.service';
import { Answer, AnswerOrigin } from '../models/Answer';

export type ChatMessage =
  | { kind: 'user'; content: string }
  | { kind: 'answer'; content: string; answer: Answer }
  | { kind: 'error'; content: string };

const ORIGIN_LABELS: Record<AnswerOrigin, string> = {
  local_qa: 'Extracted from course notes',
  llm_explanation: 'AI explanation of course notes',
  llm_fallback: 'AI answer from course notes',
  simulated_fallback: 'Fallback answer (simulated)',
  question_policy: 'Not answered from course material'
};

@Component({
    selector: 'app-chat-box',
    templateUrl: './chat-box.component.html',
    styleUrls: ['./chat-box.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class ChatBoxComponent implements AfterViewChecked {
  @ViewChild('log') private log?: ElementRef<HTMLElement>;
  @ViewChild('input') private input?: ElementRef<HTMLTextAreaElement>;

  readonly maxLength = MAX_QUESTION_LENGTH;
  // Question starters that work for any course; the student completes them.
  readonly starters = [
    'Explain ',
    'What is ',
    'What is the difference between ',
    'How does '
  ];
  messages: ChatMessage[] = [];
  newMessage = '';
  pending = false;
  private shouldScroll = false;

  constructor(private chatService: ChatServiceService) {}

  get canSend(): boolean {
    return !this.pending && this.newMessage.trim() !== '';
  }

  sendMessage(): void {
    if (!this.canSend) {
      return;
    }
    const question = this.newMessage.trim();
    this.newMessage = '';
    this.pending = true;
    this.addMessage({ kind: 'user', content: question });

    this.chatService.getAnswer(question).subscribe({
      next: (answer) => {
        this.pending = false;
        this.addMessage({ kind: 'answer', content: answer.answer, answer });
      },
      error: (error: Error) => {
        this.pending = false;
        this.addMessage({ kind: 'error', content: error.message });
      }
    });
  }

  askSuggested(topic: string): void {
    this.ask(`Explain ${topic}.`);
  }

  ask(question: string): void {
    if (this.pending) {
      return;
    }
    this.newMessage = question;
    this.sendMessage();
    this.focusInput();
  }

  prefill(start: string): void {
    this.newMessage = start;
    this.focusInput();
    // Wait for ngModel to write the text, then put the cursor after it.
    setTimeout(() => {
      const input = this.input?.nativeElement;
      input?.setSelectionRange(input.value.length, input.value.length);
    });
  }

  focusInput(): void {
    const input = this.input?.nativeElement;
    input?.scrollIntoView({ behavior: 'smooth', block: 'center' });
    input?.focus({ preventScroll: true });
  }

  clearChat(): void {
    if (!this.pending) {
      this.messages = [];
      this.focusInput();
    }
  }

  onEnter(event: Event): void {
    // Enter sends; Shift + Enter keeps the default new line.
    if (!(event as KeyboardEvent).shiftKey) {
      event.preventDefault();
      this.sendMessage();
    }
  }

  originLabel(answer: Answer): string {
    if (answer.abstained) {
      return ORIGIN_LABELS.question_policy;
    }
    const label = ORIGIN_LABELS[answer.source] ?? '';
    // A cached answer keeps its original origin but made no new model call.
    return label && answer.cache_hit ? `${label} (cached)` : label;
  }

  cacheLabel(answer: Answer): string {
    if (!answer.cache_hit) {
      return '';
    }
    if (answer.cache_match_type === 'semantic' && answer.cache_similarity !== undefined) {
      return `Similar to “${answer.cache_matched_question}” (${answer.cache_similarity.toFixed(2)})`;
    }
    return 'Same question asked before';
  }

  ngAfterViewChecked(): void {
    this.resizeInput();
    if (this.shouldScroll && this.log) {
      const el = this.log.nativeElement;
      el.scrollTop = el.scrollHeight;
      this.shouldScroll = false;
    }
  }

  private resizeInput(): void {
    const input = this.input?.nativeElement;
    if (input) {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
    }
  }

  private addMessage(message: ChatMessage): void {
    this.messages.push(message);
    this.shouldScroll = true;
  }
}
