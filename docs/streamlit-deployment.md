# Streamlit Community Cloud — Deployment Guide

The dashboard is a single Python file. Streamlit Community Cloud runs it from
your GitHub repo for free, on a public HTTPS URL, and redeploys on every push.

---

## Concepts worth knowing first

If you've written Python but not Streamlit, three things will surprise you:

**1. The whole script re-runs on every interaction.** Not a callback — the
entire file, top to bottom, every time you click a button or type in a box.
That's why `load_claims()` is wrapped in `@st.cache_data(ttl=45)`: without it,
every keystroke in the lookup box would trigger a fresh Google Sheets API call
and you'd hit the rate limit within a minute.

**2. There are two different cache decorators.**
- `@st.cache_data` — for *values* (DataFrames, dicts). Copied per session.
- `@st.cache_resource` — for *connections* (the authorised gspread client).
  Shared globally, never copied, and not required to be serialisable.

Using `cache_data` on a database connection is a classic beginner bug; it tries
to pickle the connection and fails.

**3. `st.secrets` reads a TOML file that must never be committed.** Locally it's
`.streamlit/secrets.toml`. On Community Cloud you paste the same content into a
web form and Streamlit injects it at runtime. Same `st.secrets["…"]` code either
way.

---

## 1. Push to GitHub

The repo must be **public** for the free Community Cloud tier.

```bash
git remote add origin https://github.com/<you>/claimline-ai-voice-agent.git
git branch -M main
git push -u origin main
```

**Before pushing, confirm no secrets are staged:**

```bash
git status --porcelain | grep -i "secret\|credential\|\.json$"
```

Should return nothing except the two files in `n8n/`. `.gitignore` already
excludes `.streamlit/secrets.toml` and stray `*.json` key files, but verify —
a leaked service-account key can't be un-leaked by deleting the commit.

## 2. Deploy

1. Go to **https://share.streamlit.io** and sign in with GitHub.
2. **Create app → Deploy a public app from GitHub**.
3. Fill in:
   - **Repository:** `<you>/claimline-ai-voice-agent`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
   - **App URL:** pick a subdomain, e.g. `claimline-ai`
4. Click **Advanced settings** *before* deploying and set **Python version** to
   3.11 or 3.12.
5. **Deploy.**

First build takes 2–4 minutes while it installs `requirements.txt`.

**Expected first result:** the page loads, the hero and charts render, and you
see a yellow *"Showing bundled sample data"* notice plus a *"Voice widget not
configured"* notice. That's correct — you haven't added secrets yet. The app is
written to degrade gracefully rather than crash, so you can confirm the deploy
worked before dealing with credentials.

## 3. Add the secrets

1. On your deployed app: **⋮ (top right) → Settings → Secrets**.
2. Open your local `.streamlit/secrets.toml`, copy **the entire contents**, and
   paste into the box. (Paste the file *content*, not a file upload — and not
   the `.example` file.)
3. **Save.** The app reboots automatically.

After the reboot both yellow notices should be gone, the call button should
appear bottom-right, and the table should show live Google Sheets data.

## 4. Verify end to end

1. Open the public URL.
2. Click the call widget, allow microphone access.
3. Say: *"I need to file a claim, my policy is POL-10234."*
4. Complete the claim; note the claim ID.
5. Click **↻ Refresh data** on the dashboard.
6. The new claim should appear in the table, the charts should update, and
   looking up that claim ID should return its details.
7. Check your inbox for the confirmation email from Workflow B.

## 5. Put the URL in the README

Replace the placeholder in `README.md` with your real app URL and push.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` on boot | Package missing from `requirements.txt` | Add it, push; Cloud rebuilds automatically |
| Still shows "sample data" after adding secrets | TOML typo, or sheet not shared | Check the app **Logs**; the most likely cause is the sheet not being shared with the service account's `client_email` |
| `Could not deserialize key data` | `private_key` newlines were expanded | Must be a single line with literal `\n`, in triple quotes |
| `SpreadsheetNotFound` | Wrong Spreadsheet ID | Re-copy it from the sheet URL, between `/d/` and `/edit`. (Drive API is *not* required — `open_by_key` uses the Sheets API only.) |
| `APIError 403` | Sheet not shared with the service account | Share → paste `client_email` → Viewer |
| Call button missing | Retell secrets absent, or key/agent-id swapped | `public_key` starts `public_key_`, `agent_id` starts `agent_` |
| Call button appears, nothing happens on click | Microphone blocked | Must be HTTPS (Cloud is) and permission granted; check site permissions in the address bar |
| App sleeps / "get this app back up" | Free tier hibernates after ~7 days idle | Click the wake button. Visit it before showing anyone. |
| Charts look right locally, wrong on Cloud | Different plotly version | `requirements.txt` floors are there for this; bump if needed |

### Reading the logs

**Manage app** (bottom right of the deployed page) opens the live log stream.
Every Python exception, install failure and reboot shows there. It's the first
place to look for anything unexpected.

---

## Running it locally

```bash
git clone https://github.com/<you>/claimline-ai-voice-agent.git
cd claimline-ai-voice-agent
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # then fill it in
streamlit run streamlit_app.py
```

It runs without any secrets at all — you'll get the bundled sample data and no
call widget, which is enough to work on layout and charts.

**One local caveat:** the Retell widget needs a secure context. `localhost`
counts as secure, so the widget loads, but microphone access can still be
blocked depending on browser settings. Verify voice on the deployed HTTPS URL.
