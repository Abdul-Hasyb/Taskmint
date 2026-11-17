# Taskmint 🌿

Paste any message or note (English, Urdu or Roman Urdu) and Taskmint's AI turns it into tasks. Each task comes with the quote it came from, and nothing is saved until you approve it. It works for a personal to-do list or for a small team ("Bilal has to send the invoice by Friday").

## Features

- **AI task finder** (Google Gemini). Understands dates like *kal*, *parso* and *shaam*, and who each task is for.
- **Tasks, people and due dates**: assign work, set a day and a time, mark tasks done.
- **Reminders**: browser pop-ups and email. With a time you get one an hour before, one at the time, and one an hour after if the task isn't done. No reminders during quiet hours.
- **Calendar, analytics and people views**, with charts drawn by hand in SVG.
- **Security**: Argon2 passwords, JWT, rate limits, account lockout, email verification, strict CSP and security headers, size and number caps, and 140+ automated tests, including attack tests.

## Tech

FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL (Supabase) · Pydantic v2 · Gemini (google-genai) · Brevo email · vanilla JS · pytest

## Run it locally

```bash
python -m venv venv
venv\Scripts\activate          # Windows (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env         # then fill in your own values
alembic upgrade head
uvicorn app.main:app --reload
pytest                         # the tests use a throwaway database, never the real one
```

## Deploy (Render, free plan)

| Setting | Value |
|---|---|
| Build command | `pip install -r requirements.txt && alembic upgrade head` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health` |

Environment variables are the ones in `.env.example`, plus:

- `DATABASE_URL`: Supabase **Session pooler** string (Render has no IPv6, so the direct `db.…supabase.co` address won't connect).
- `APP_URL`: the live `https://….onrender.com` address.
- `ENABLE_DOCS=0`: hide `/docs`.
- `CLIENT_IP_HEADER=True-Client-IP`: the real visitor IP, as set by Cloudflare in front of Render.

The free plan sleeps after 15 minutes without visitors. A free cron pinger on `/health` every 10 minutes keeps it awake, and it keeps reminder emails on time.
