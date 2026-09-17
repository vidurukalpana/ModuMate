# ModuMate
ModuMate is a cost-effective, LLM-powered intelligent tutor designed for a single course module at a university or school. It helps students understand course concepts, ask questions, and practise at their own pace through personalised, course-focused support.

## Application structure

- `code/backend`: Flask API, question-answering models, response cache, and course dataset. See its README for setup.
- `code/chat-app`: Angular chat interface, which calls the Flask API.
- `code/utils`: research notebooks, prototype utilities, and supporting datasets.
- `docs`: project documentation.

The current application requires no API keys or database credentials. The bundled
Moodle source is not required by either app and has been removed. Research and
prototype utilities remain in `code/utils`. The backend retains its course data
in `code/backend/text_files`.

Keep any future private credentials on the backend. Local `.env` files are ignored
by Git; commit only `.env.example` files with placeholders. Never include private
credentials in Angular code or its environment configuration.
