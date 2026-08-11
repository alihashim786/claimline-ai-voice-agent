# n8n Setup Guide — importing and publishing both workflows

Two workflows, deliberately split by *latency budget*:

- **Workflow A** runs **during** the call. Retell blocks the conversation
  waiting for its response, so everything in it must be fast and it must always
  reply.
- **Workflow B** runs **after** the call. Nothing is waiting on it, so it can
  take its time sending email and writing analytics.

This is the core architectural idea of the project. Anything a caller has to
wait for goes in A; everything else goes in B.

> **Prefer clicking to reading?** [`n8n-walkthrough.md`](n8n-walkthrough.md) is
> the same build as a click-by-click guide, including how to test both
> workflows inside the n8n editor with pinned data instead of using a terminal.

---

## 1. Import both workflows

For each file in `n8n/`:

1. n8n → **Workflows** → **Add workflow** → the **⋯** menu (top right) →
   **Import from File…**
2. Select `n8n/workflow-a-mid-call-action-router.json`, then repeat for
   `workflow-b-post-call-confirmation.json`.

You'll see red warning triangles on the Google Sheets and Gmail nodes. That's
expected — credentials were intentionally left out of the export so you pick
your own rather than chasing a broken credential reference.

## 2. Set the Sheet ID (five nodes)

Open each Google Sheets node and replace `PASTE_YOUR_GOOGLE_SHEET_ID_HERE` in
the **Document** field with your real Spreadsheet ID — three nodes in Workflow A,
two in Workflow B. Import from `n8n/local/` instead and this is already done.

> **Keep it a literal ID, never an expression.** It is tempting to hold the ID
> in one Set node and reference it everywhere as
> `{{ $('Config').first().json.sheet_id }}`. That breaks the node: n8n populates
> the **Sheet** and **Column to match on** dropdowns by reading your spreadsheet
> *while you are editing*, and an expression cannot be resolved at design time —
> there is no execution data yet. The dropdowns come up empty, the column value
> is silently dropped, and at runtime you get `The column "" could not be found`,
> which points at a column when the real cause is the document field.
>
> This project shipped the Set-node version first and hit exactly that. Five
> literal values beat one clever reference.

## 3. Attach credentials

| Node | Credential |
|---|---|
| Workflow A → `Read Policies`, `Append Claim Row`, `Read Claims` | Google Sheets OAuth2 |
| Workflow B → `Log Claim Filed`, `Log No Claim` | Google Sheets OAuth2 (same one) |
| Workflow B → `Gmail — Send Confirmation` | Gmail OAuth2 |

Create the first one via **Create new**, then select it from the dropdown in the
rest.

For the Gmail node, also set the **From / sender** to your own Gmail address.

## 4. Publish both, and copy the PRODUCTION URLs

Click **Publish** on each workflow. In n8n 2.0 this replaced the old
Active/Inactive toggle — **Save alone does not make a workflow live.**

Then open each Webhook node and copy the **Production URL**:

```
Workflow A:  https://<your-instance>.app.n8n.cloud/webhook/claimline-action
Workflow B:  https://<your-instance>.app.n8n.cloud/webhook/claimline-post-call
```

> ### The Test-URL trap
> Every webhook node shows two URLs:
>
> | | Path | Behaviour |
> |---|---|---|
> | Test URL | `/webhook-test/…` | Only live while you're in the editor with **Listen for test event** armed. Accepts **one** request, then goes dead. |
> | Production URL | `/webhook/…` | Always live once the workflow is Published. |
>
> Paste a Test URL into Retell and your agent works perfectly exactly once, then
> starts failing with no obvious change. **Always use the Production URL.**
>
> The Test URL is still genuinely useful — it's the only way to get a real
> payload into the editor so n8n can populate the field-picker autocomplete.
> Use it while building, switch to Production before wiring Retell.

---

## 5. Test Workflow A without Retell

You can exercise all three branches with `curl` before the agent exists. Replace
the URL with yours.

```bash
# Valid policy
curl -X POST "https://<you>.app.n8n.cloud/webhook/claimline-action" \
  -H "Content-Type: application/json" \
  -d '{"args":{"action":"validate_policy","policy_number":"POL-10234"}}'
# -> {"valid":true,"holder_name":"Sara Ahmed","coverage_type":"Auto",...}

# Invalid policy
curl -X POST "https://<you>.app.n8n.cloud/webhook/claimline-action" \
  -H "Content-Type: application/json" \
  -d '{"args":{"action":"validate_policy","policy_number":"POL-99999"}}'
# -> {"valid":false,"reason":"not_found",...}

# Create a claim that must triage as Urgent
curl -X POST "https://<you>.app.n8n.cloud/webhook/claimline-action" \
  -H "Content-Type: application/json" \
  -d '{"args":{"action":"create_claim","policy_number":"POL-10234",
       "holder_name":"Sara Ahmed","incident_type":"Accident",
       "incident_date":"2026-08-05",
       "description":"Rear-ended at a signal, my wife was taken to hospital by ambulance",
       "email":"you@example.com","urgency":"Standard"}}'
# -> {"success":true,"claim_id":"CLM-xxxxxx","urgency":"Urgent",...}
#    Note it returned Urgent even though Standard was sent -- that is the
#    server-side keyword rule overriding the caller-facing guess.

# Status lookup
curl -X POST "https://<you>.app.n8n.cloud/webhook/claimline-action" \
  -H "Content-Type: application/json" \
  -d '{"args":{"action":"check_status","claim_id":"CLM-000001"}}'
# -> {"found":true,"status":"Filed",...}
```

Test the fuzzy-input repair too — these should all resolve to the same policy:

```bash
-d '{"args":{"action":"validate_policy","policy_number":"pol 10234"}}'
-d '{"args":{"action":"validate_policy","policy_number":"10234"}}'
```

Each call should also leave a green execution in the **Executions** tab, and the
create_claim calls should append a row to the `Claims` tab.

## 6. Test Workflow B without Retell

```bash
curl -X POST "https://<you>.app.n8n.cloud/webhook/claimline-post-call" \
  -H "Content-Type: application/json" \
  -d '{"event":"call_analyzed","call":{"call_id":"test_123",
       "call_analysis":{"custom_analysis_data":{
         "claim_filed":true,"claim_id":"CLM-000001","urgency":"Urgent",
         "name":"Sara Ahmed","email":"you@example.com","incident_type":"Accident"}}}}'
```

Expect: an email in your inbox, and a new row in the `Analytics` tab. Then flip
`"claim_filed"` to `false` and confirm you get **no** email but **do** get an
analytics row.

---

## How Workflow A works

```
Webhook (POST, responseMode = responseNode)
  → Normalize Request   flatten Retell's {args:{…}} wrapper; repair POL-/CLM- formats
  → Switch on action
       ├─ validate_policy → Read Policies  → Build Validate Response → Respond
       ├─ create_claim    → Generate Claim ID & Triage → Append Claim Row → Build Claim Response → Respond
       ├─ check_status    → Read Claims     → Build Status Response   → Respond
       └─ fallback        → Respond (unknown_action)
```

Three things in there are load-bearing:

**`responseMode: responseNode`** — tells n8n "don't reply automatically, wait
for a Respond to Webhook node". Without it n8n answers instantly with a generic
acknowledgement and Retell never receives the claim ID.

**Lookups read the whole tab and match in a Code node** — they do not use the
Sheets node's row filter. That filter's "Column to match on" is a dropdown
populated by reading your sheet *at edit time*, and it can import empty, failing
at runtime as `The column "" could not be found`. A `.find()` in JavaScript
cannot be blanked by a dropdown. `Always Output Data` is still on so an empty
tab produces one item rather than zero, which would stop the branch dead and
leave the caller in silence.

**Every branch ends in a Respond node, including the fallback.** In a
synchronous workflow, a path with no Respond node is a hung phone call.

## How Workflow B works

```
Webhook (POST, responds immediately)
  → Flatten Retell Payload      call.call_analysis.custom_analysis_data → flat fields
  → IF claim_filed == true
       ├─ true  → Gmail: send confirmation → Analytics: log row (claim_filed = true)
       └─ false → Analytics: log row (claim_filed = false)
```

**Responds immediately** rather than after the last node: Retell only needs a
200 to mark the event delivered. Making it wait for Gmail risks a Retell timeout
and retry → duplicate confirmation emails.

**The Gmail node has `On Error: Continue`.** A bad or missing caller email
shouldn't stop the analytics row from being written — the dashboard should still
show that the call happened.

**The analytics node reads `$('Flatten Retell Payload')`, not `$json`.** This
catches out most n8n beginners: each node *replaces* `$json` with its own
output, so after Gmail runs, `$json` is Gmail's API response. `$('Node Name')`
reaches back to a specific earlier node's data.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Retell function times out | Workflow not Published, or Test URL in use | Publish; use the `/webhook/` URL |
| Works once then stops | Test URL | Same as above |
| Appended rows are blank | Sheet headers don't match | Headers must match `data/Claims-Template.csv` exactly |
| `The column "" could not be found` | The Document field holds an expression, so the column dropdown never loaded | Put a literal Sheet ID in the Document field, then re-pick the Sheet and the Column to match on |
| `check_status` always "not found" | Claim ID formatting | Normalize node pads to 6 digits; check the sheet stores `CLM-000001`, not `1` |
| Execution green but no reply reached the agent | Branch has no Respond node | Every Switch output needs one |
| No execution appears at all | Wrong URL, or workflow unpublished | Compare against the Webhook node's Production URL |
| Duplicate confirmation emails | Workflow B responding too late | Webhook response mode must be **Immediately** |
| Expression shows `[undefined]` | Node hasn't seen a payload yet | Fire one test request so n8n learns the schema |
