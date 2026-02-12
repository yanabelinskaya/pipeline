# Shift Schedule

## Quick start
1) Create and activate a virtual environment:
   - `python3 -m venv .venv`
   - `source .venv/bin/activate`
2) Install dependencies:
   - `pip install -r requirements.txt`
3) Create local environment file:
   - `cp .env.example .env`
   - Fill in values in `.env` (database + email)
4) Run migrations:
   - `python manage.py migrate`
5) Start the server:
   - `python manage.py runserver`

## Environment variables
Settings are loaded from `.env` (built-in loader; `python-dotenv` is optional).

Important variables:
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`
- `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_USE_SSL`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`

## Project structure (important parts)
- `manage.py` — Django entry point
- `schedule_api/` — project settings and urls
- `accounts/` — custom user app
- `templates/` — HTML templates
- `static/` — static assets

## Notes
- `.env` is ignored by git. Do not commit secrets.
- `venv/` or `.venv/` should stay local (ignored by git).
