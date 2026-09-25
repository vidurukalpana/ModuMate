import { AfterViewChecked, Component, ElementRef, ViewChild, ChangeDetectionStrategy } from '@angular/core';

import { ChatServiceService, MAX_QUESTION_LENGTH } from '../chat-service.service';
import { Answer, AnswerOrigin } from '../models/Answer';

export type ChatMessage =
  | { kind: 'user'; content: string }
  | { kind: 'answer'; content: string; answer: Answer }
  | { kind: 'error'; content: string };

const ORIGIN_LABELS: Record<AnswerOrigin, string> = {
  local_qa: 'From course material',
  llm_fallback: 'Generated from course material',
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

  readonly maxLength = MAX_QUESTION_LENGTH;
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
    this.newMessage = `Explain ${topic}.`;
    this.sendMessage();
  }

  originLabel(answer: Answer): string {
    return ORIGIN_LABELS[answer.source] ?? '';
  }

  ngAfterViewChecked(): void {
    if (this.shouldScroll && this.log) {
      const el = this.log.nativeElement;
      el.scrollTop = el.scrollHeight;
      this.shouldScroll = false;
    }
  }

  private addMessage(message: ChatMessage): void {
    this.messages.push(message);
    this.shouldScroll = true;
  }
}
