import { Component, ChangeDetectionStrategy } from '@angular/core';

interface Topic {
  icon: string;
  title: string;
  question: string;
}

@Component({
    selector: 'app-root',
    templateUrl: './app.component.html',
    styleUrls: ['./app.component.css'],
    changeDetection: ChangeDetectionStrategy.Eager,
    standalone: false
})
export class AppComponent {
  readonly topics: Topic[] = [
    { icon: '💡', title: 'Explain a concept', question: 'Explain ' },
    { icon: '📖', title: 'Define a term', question: 'What is ' },
    { icon: '⚖️', title: 'Compare two ideas', question: 'What is the difference between ' },
    { icon: '⚙️', title: 'How it works', question: 'How does ' },
    { icon: '🤔', title: 'Why it matters', question: 'Why is ' },
    { icon: '📝', title: 'Describe a topic', question: 'Describe ' }
  ];
}
