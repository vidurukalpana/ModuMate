# ModuMate chat app

Angular 22 chat interface for the ModuMate backend. Students ask questions about
the multiprocessors course material; the app posts them to the Flask `/api`
endpoint and shows the answer, where it came from, and the supporting excerpts.

## Requirements

- Node 26 (see `.nvmrc`). Angular 22 also supports Node 22.22+ and 24.15+.
- The backend running at `http://localhost:5000` (see `../backend/README.md`).

## Commands

```bash
npm ci                                                 # install dependencies
npm start                                              # dev server at http://localhost:4200
npm run build -- --configuration production            # build to dist/chat-app/browser
npm test -- --watch=false --browsers=ChromeHeadless    # unit tests
```

## Configuration

The backend base URL is set in `src/environments/environment.ts` (`apiBaseUrl`).
Do not put credentials in this app; anything in the Angular bundle is public.

## Behavior

- Enter or **Send** submits; the input clears immediately and sending is disabled
  until the current answer arrives. Questions are limited to 2,000 characters,
  matching the backend.
- Each answer is labelled with its origin: extracted from the notes, AI explanation
  of an extracted answer (the extracted span is shown underneath), AI answer from
  course notes (when nothing could be extracted), or not answered.
- Cached answers keep their original label with "(cached)" added, since no new
  model call was made, plus a badge showing whether the same question or a similar
  one (with its similarity score) was matched.
- Source excerpts returned by the backend are listed under each answer.
- Policy responses show the backend's suggested topics as one-click follow-ups.
- `backend_busy` (503) responses are retried up to twice, honoring `Retry-After`.
  Other failures (backend unreachable, validation errors, timeouts) appear
  in the conversation as readable error messages.
