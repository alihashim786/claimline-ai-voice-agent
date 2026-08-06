# Google Sheets Setup — the data layer

ClaimLine uses one Google Spreadsheet with three tabs as its database. Two
different systems talk to it, with **deliberately different permissions**:

| Consumer | Auth | Access |
|---|---|---|
| n8n (Workflows A & B) | Your Google account, via OAuth | Read **and write** |
| Streamlit dashboard | A service account | **Read only** |

The dashboard is public. Giving it a read-only credential means that even in the
worst case — a secrets leak — nobody can edit or delete your claims data through
it. The scopes in `streamlit_app.py` are `spreadsheets.readonly` and
`drive.readonly` for exactly this reason.

---

## 1. Create the spreadsheet

1. Go to **https://sheets.new**.
2. Rename it **`ClaimLine-Data`** (top-left).
3. Create three tabs named **exactly** `Policies`, `Claims`, `Analytics`.
   Tab names are matched case-sensitively by n8n and by the dashboard —
   `claims` will not find `Claims`.

## 2. Import the provided data

For each tab: **File → Import → Upload**, pick the CSV, and choose
**"Replace current sheet"** with the correct tab selected first.

| Tab | File | Contents |
|---|---|---|
| `Policies` | `data/Policies-Seed-Data.csv` | 10 fictional policies — the "existing customers" `validate_policy` checks against |
| `Claims` | `data/Claims-Template.csv` | Header row + one example claim, so the columns exist before the agent appends |
| `Analytics` | `data/Analytics-Template.csv` | Header row + one example row |

> **Do not retype the headers by hand.** n8n's Google Sheets node maps by
> column *name*. A trailing space in `policy_number ` produces an empty column
> in every appended row, and it is invisible in the UI.

Verify: `Policies` row 2 should read `POL-10234, Sara Ahmed, Auto, 2027-01-01`.

## 3. Get the Spreadsheet ID

From the URL:

```
https://docs.google.com/spreadsheets/d/1AbCdEfGh...XyZ/edit#gid=0
                                       └──── this is the ID ────┘
```

You need it in three places: Workflow A's `Config` node, Workflow B's `Config`
node, and Streamlit secrets.

---

## 4. Create the read-only service account (for the dashboard)

A service account is a non-human Google identity with its own email address. The
dashboard authenticates as *it*, not as you — so it keeps working when you're
logged out, and it can be revoked without touching your own account.

1. Go to **https://console.cloud.google.com** and create a project (any name,
   e.g. `claimline-ai`). No billing card is needed for this.
2. **APIs & Services → Library** → enable **Google Sheets API**.
3. Same Library → enable **Google Drive API**.
   *(gspread opens sheets through Drive metadata; skipping this gives a
   confusing `SpreadsheetNotFound` even when the ID is correct.)*
4. **APIs & Services → Credentials → Create Credentials → Service account**.
   - Name: `claimline-dashboard`
   - Skip the optional role/user grants — **do not** give it a project role. It
     needs no project permissions at all; access comes from sharing the sheet
     with it in step 6.
5. Click the new service account → **Keys → Add Key → Create new key → JSON**.
   A `.json` file downloads. **This file is a private key.** It is already
   covered by `.gitignore` — keep it out of the repo permanently.
6. Open the JSON, copy the `client_email` value (it looks like
   `claimline-dashboard@claimline-ai.iam.gserviceaccount.com`).
7. Back in the Google Sheet: **Share** → paste that email → set to **Viewer** →
   untick "Notify people" → **Share**.

**Step 7 is the one everyone forgets.** A service account is a separate identity;
your own access to the sheet grants it nothing. Skip this and every dashboard
read returns a 403 no matter how correct the credentials are.

## 5. Convert the JSON key into Streamlit secrets

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and move
each value across from the JSON file.

The only tricky field is `private_key`. In the JSON it's one long line
containing literal `\n` sequences:

```json
"private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQ...\n-----END PRIVATE KEY-----\n"
```

In TOML it goes inside triple quotes, **keeping the `\n` as literal backslash-n**
— do not expand them into real line breaks:

```toml
private_key = """-----BEGIN PRIVATE KEY-----\nMIIEvQ...\n-----END PRIVATE KEY-----\n"""
```

If you get `ValueError: Could not deserialize key data`, this is why.

---

## 6. Connect n8n to Sheets (read/write)

n8n uses a different, simpler path — your own Google account via OAuth:

1. In either workflow, open any Google Sheets node → **Credential to connect
   with → Create new**.
2. Choose **Google Sheets OAuth2 API** → **Sign in with Google** → approve.
3. Reuse that one credential in all five Google Sheets nodes across both
   workflows.

n8n Cloud handles the OAuth app registration for you, so there's no Cloud
Console work needed on this side.

---

## Checklist

- [ ] Spreadsheet named `ClaimLine-Data` with tabs `Policies`, `Claims`, `Analytics`
- [ ] All three CSVs imported, headers untouched
- [ ] Spreadsheet ID copied
- [ ] Sheets API **and** Drive API enabled
- [ ] Service account JSON key downloaded (and never committed)
- [ ] Sheet **shared** with the service account's `client_email` as Viewer
- [ ] n8n Google Sheets OAuth credential created and selected in all five nodes
