# Harbour House – Hotel Management System (Flask)

Rooms, guests, bookings with availability checking, check-in / check-out, and a
live "key rack" dashboard.

## Run in VS Code
```bash
python -m venv .venv
.venv\Scripts\activate        # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
python app.py                 # http://127.0.0.1:5000
```
Locally it uses a SQLite file (`hotel.db`) that is created and seeded with 12 rooms.

## Deploy to Vercel
1. Push the folder to GitHub (`git init`, `git add .`, `git commit`, push).
2. On vercel.com choose **Add New → Project**, import the repo, and deploy.
   (Or from the terminal: `npm i -g vercel` then `vercel`.)
3. **Add a database**, or your data will reset. Vercel functions can't keep files,
   so SQLite only survives briefly in `/tmp`. In your Vercel project open
   **Storage**, add a Postgres database (Neon) or use Supabase, and make sure the
   `DATABASE_URL` environment variable is set. Tables and sample rooms are
   created automatically on first load.
4. Set `SECRET_KEY` (any long random string) and optionally `CURRENCY` (e.g. `₹`)
   under **Settings → Environment Variables**, then redeploy.

## Structure
- `app.py` – Flask app, models, routes
- `templates/` – Jinja pages
- `static/style.css` – styling
- `vercel.json` – tells Vercel to run `app.py` with the Python runtime
