# n8n — Click-by-Click Walkthrough

A complete, from-scratch build of both workflows, including how to test them
**inside the n8n editor** without any command line.

Follow it in order. Each phase ends with a checkpoint you can verify before
moving on, so a mistake never travels more than one phase.

**Time:** about 25 minutes.

---

## Phase 0 — Clean slate

Old copies of these workflows will fight the new ones for the same webhook
path. Two workflows cannot both own `/webhook/claimline-action`, and n8n
refuses to activate the second one — which shows up as a greyed-out Publish
button with no obvious cause.

1. Left sidebar → **Overview** → **Workflows**
2. Delete **every** existing ClaimLine workflow: hover the row → **⋯** →
   **Delete**
3. Confirm the list has no ClaimLine entries left

> Your **credentials are not stored inside workflows** — they live at the
> account level. Deleting workflows does not delete your Google Sheets or Gmail
> connections, and you will re-select them from a dropdown in Phase 2.

---

## Phase 1 — Import Workflow A

1. **Overview → Workflows → Create Workflow** (top right)
2. On the empty canvas, click the **⋯** menu (top-right corner)
3. Choose **Import from File…**
4. Select:
   `d:\1. Voice AI Projects\claimline-ai-voice-agent\n8n\local\workflow-a-mid-call-action-router.json`

   > Use the **`n8n/local/`** copy — your Google Sheet ID is already filled in.
   > The `n8n/` copy has a placeholder instead.

5. The canvas fills with 14 nodes. Press **Ctrl+S** to save.

**Checkpoint.** You should see this shape — one webhook fanning into four
branches, each ending in a Respond node:

```
Webhook → Normalize Request → Route by Action ─┬─ Read Policies → Build Validate Response → Respond — Policy Validation
                                               ├─ Generate Claim ID & Triage → Append Claim Row → Build Claim Response → Respond — Claim Created
                                               ├─ Read Claims → Build Status Response → Respond — Claim Status
                                               └─ Respond — Unknown Action
```

The three Google Sheets nodes will show a red warning triangle. That is
expected — they have no credential yet. Nothing else should be marked.

---

## Phase 2 — Connect the Google Sheets credential

Three nodes need it: **Read Policies**, **Append Claim Row**, **Read Claims**.

For each one:

1. **Double-click** the node to open it
2. At the very **top** of the panel: **Credential to connect with**
3. Open the dropdown:
   - Your existing credential should be listed (often *"Google Sheets
     account"*) → **select it**
   - Nothing listed? → **+ Create new credential** → **Google Sheets OAuth2
     API** → **Sign in with Google** → pick the account that **owns the
     ClaimLine-Data sheet** → **Allow**
4. **Do not touch anything else in the panel.** Leave Resource, Operation,
   Document and Sheet exactly as imported.
5. Click **Back to canvas** (top left of the panel)

> **If the Google sign-in popup never appears, your browser blocked it.** The
> credential then saves in a half-finished state that looks fine on the canvas
> and fails at runtime. Allow popups for n8n and redo it.

**Checkpoint.** Open **Read Policies** again and click the **Sheet** field's
dropdown. If it lists `Policies`, `Claims`, `Analytics`, your credential is
genuinely connected — n8n could only read those names by successfully calling
Google. **Then press Escape without changing anything.**

That check is worth doing. It is the difference between a credential that is
selected and one that actually works.

All three red triangles should now be gone. Press **Ctrl+S**.

---

## Phase 3 — Test Workflow A inside n8n

No command line needed. We give the Webhook node fake output ("pinned data"),
then run the workflow by hand.

### Test 1 — a valid policy

1. **Double-click the `Webhook` node**
2. Look at the **OUTPUT** panel on the right. Click the **pencil / Edit Output**
   icon at its top
3. Delete whatever is there and paste exactly this:

```json
[
  {
    "body": {
      "args": {
        "action": "validate_policy",
        "policy_number": "POL-10234"
      }
    }
  }
]
```

4. Click **Save** in that little editor, then **Back to canvas**.
   The Webhook node now shows a small **purple pin** icon — that is pinned data.
5. Click **Execute workflow** (button at the bottom-centre of the canvas)

**What should happen:** the top branch lights up green — `Read Policies` →
`Build Validate Response` → `Respond — Policy Validation`.

6. **Double-click `Build Validate Response`** and read its OUTPUT:

```json
{
  "result": "valid",
  "valid": true,
  "policy_number": "POL-10234",
  "holder_name": "Sara Ahmed",
  "coverage_type": "Auto"
}
```

`"result": "valid"` and `"holder_name": "Sara Ahmed"` is the pass condition.
That name came out of your spreadsheet, so this proves the whole path.

### Test 2 — an unknown policy

Same steps, but change the pinned JSON's `policy_number` to `"POL-99999"` and
Execute again.

Expect `"result": "not_found"`, `"valid": false` — and note the workflow still
finishes **green**, not red. A policy that does not exist is a normal answer,
not an error. If this branch went red, the agent would tell callers "something
went wrong" instead of "I can't find that policy".

### Test 3 — file a claim, and watch the triage override

Pin this instead:

```json
[
  {
    "body": {
      "args": {
        "action": "create_claim",
        "policy_number": "POL-10234",
        "holder_name": "Sara Ahmed",
        "incident_type": "Accident",
        "incident_date": "2026-08-05",
        "description": "Rear-ended at a signal, my wife was taken to hospital by ambulance",
        "email": "your.real@gmail.com",
        "urgency": "Standard"
      }
    }
  }
]
```

Execute, then open **Build Claim Response**:

```json
{ "result": "urgent", "urgency": "Urgent", "claim_id": "CLM-xxxxxx", "status": "Filed" }
```

**Look closely: we sent `"urgency": "Standard"` and got back `"Urgent"`.**
That is the server-side keyword rule reading the caller's own words —
*hospital*, *ambulance* — and overruling the agent's guess. Urgency drives a
real SLA (24–48h vs 5–7 days), so it is decided by a rule that gives the same
answer every time, not by a model that might not.

Now open your **Google Sheet → Claims tab**. A new row is there, urgency
`Urgent`. That is the write path confirmed.

### Test 4 — check a status

```json
[{ "body": { "args": { "action": "check_status", "claim_id": "CLM-000001" } } }]
```

Expect `"result": "found"`, `"status": "Filed"` from **Build Status Response**.

Then try `"CLM-999999"` → `"result": "not_found"`, still green.

### Before moving on — unpin

Click the **Webhook** node and click the **pin icon** to remove the pinned
data (or **Unpin** in the output panel).

Pinned data is only ever used in manual executions and is ignored in
production, so it cannot break your live webhook — but leaving it makes the
editor show stale output forever, which is confusing later.

Press **Ctrl+S**.

---

## Phase 4 — Publish Workflow A

1. Press **Ctrl+S** one more time. **Publish stays greyed out while there are
   unsaved changes** — this is the single most common reason it looks broken.
2. Click **Publish** (top-right, next to the version counter)

**If Publish is still disabled**, in order:

| Check | What it means |
|---|---|
| Hover the button | n8n shows a tooltip with the actual reason — trust it over guesswork |
| Any node still showing a red triangle? | An invalid node blocks publishing. Usually a missing credential |
| Does the counter read `3 / 3`? | You have hit the trial's published-workflow limit. Unpublish something else |
| Two ClaimLine A workflows in the list? | They collide on the same webhook path. Delete the stale one (Phase 0) |

**Alternative route:** **Overview → Workflows** — each row has its own
**Active** toggle on the right. Flipping that does the same job and sidesteps
the button entirely.

**Checkpoint.** Open the **Webhook** node. It shows two URLs:

| | Looks like | When it works |
|---|---|---|
| Test URL | `/webhook-test/claimline-action` | Only while you have Execute workflow armed. One request, then dead |
| **Production URL** | `/webhook/claimline-action` | **Always, once published** |

Confirm the Production URL reads exactly:
`https://alihashim.app.n8n.cloud/webhook/claimline-action`

That is the URL already configured in your Retell agent, so if it matches,
there is nothing to rewire.

---

## Phase 5 — Import and connect Workflow B

1. **Overview → Workflows → Create Workflow**
2. **⋯ → Import from File…** →
   `n8n\local\workflow-b-post-call-confirmation.json`
3. **Ctrl+S**

Eight nodes:

```
Webhook (call_analyzed) → Flatten Retell Payload → IF claim_filed ─┬─ true  → Gmail — Send Confirmation → Analytics Row — Filed → Log Claim Filed
                                                                   └─ false → Analytics Row — No Claim → Log No Claim
```

Connect three credentials, same method as Phase 2:

| Node | Credential |
|---|---|
| `Log Claim Filed` | Google Sheets OAuth2 (the same one) |
| `Log No Claim` | Google Sheets OAuth2 (the same one) |
| `Gmail — Send Confirmation` | Gmail OAuth2 — **Create new** → Sign in with Google → Allow |

Gmail is a **separate** credential from Sheets even on the same Google account;
they request different permissions.

---

## Phase 6 — Test Workflow B inside n8n

### Test 5 — a claim was filed (expect an email)

Pin this on the **`Webhook (call_analyzed)`** node — note the deeper nesting,
this is the real shape Retell sends:

```json
[
  {
    "body": {
      "event": "call_analyzed",
      "call": {
        "call_id": "test_manual_1",
        "call_analysis": {
          "call_summary": "Caller filed a new claim after an accident.",
          "custom_analysis_data": {
            "claim_filed": true,
            "claim_id": "CLM-000001",
            "urgency": "Urgent",
            "name": "Sara Ahmed",
            "email": "your.real@gmail.com",
            "incident_type": "Accident"
          }
        }
      }
    }
  }
]
```

Put **your own email address** in there — this really does send mail.

Execute. Expect the **upper** branch: Gmail → Analytics Row — Filed → Log Claim
Filed.

Open **Flatten Retell Payload** and confirm `"claim_filed": true` as a real
boolean, not the string `"true"`. That node exists to dig those fields out of
Retell's deep nesting once, so no other node has to retype
`call.call_analysis.custom_analysis_data.…` and get it subtly wrong.

Then check: your **inbox** has the confirmation, and the **Analytics tab** has a
new `TRUE / Urgent / Accident` row.

### Test 6 — no claim was filed (expect NO email)

Change `"claim_filed"` to `false` and Execute.

Expect the **lower** branch only. **No email.** A new Analytics row with
`FALSE / n/a / n/a`.

Logging the no-claim calls is what makes the dashboard's volume chart
meaningful — without them you only ever see successes and cannot tell what
fraction of calls converted.

### Then

Unpin the Webhook node, **Ctrl+S**, **Publish**.

Production URL should read:
`https://alihashim.app.n8n.cloud/webhook/claimline-post-call`

---

## Phase 7 — Confirm both are live

**Overview → Workflows.** Both ClaimLine rows should show as Active/Published.

Everything from here is real traffic, so from now on use the **Executions** tab
(not the canvas) to see what happened — production runs are never drawn on the
canvas, only listed there.

---

## Phase 8 — Test from Retell

Your agent is already wired to both URLs, so nothing to configure.

1. Retell dashboard → **Agents** → **ClaimLine AI**
2. Click **Test** (top right) and choose **text mode** — it costs almost
   nothing and, unlike audio, shows every function call with its full request
   and response
3. Run these:

| Say | Expect |
|---|---|
| "What documents do I need for a home claim?" | Answered from the knowledge base. **No** function call |
| "I want to file a claim, my policy is POL-10234" | `validate_policy` returns `result: valid`; agent confirms **Sara Ahmed, Auto cover** |
| *(continue)* "I was rear-ended and my wife went to hospital by ambulance" | `create_claim` returns `result: urgent`; agent reads a claim ID back **twice** and mentions 24–48 hours |
| "Check claim CLM-000001" | `check_status` returns `result: found`, status `Filed` |
| "My policy is POL-99999" | Agent says it cannot find it and offers one retry. Must **never** reach claim creation |

4. Expand each function call in the side panel and read the **response**. That
   is where you see `result`, `holder_name`, `claim_id` — exactly what the
   flow branches on.

**If the agent says "I'm having trouble pulling up our records right now"**,
that is the flow's honest backend-failure message: the webhook did not answer.
Go to n8n → **Executions** and look at the most recent run. It specifically
does **not** say "policy not found", so you know the number was fine and the
problem is the connection.

Finally, hang up and wait about a minute for Retell's post-call analysis, then
check: confirmation **email** arrived, **Analytics** row appeared, and
[the dashboard](https://claimline-ai.streamlit.app/) shows the new claim after
you press **Refresh data**.

---

## Quick reference

| Symptom | Cause | Fix |
|---|---|---|
| `404 ... webhook not registered` | Workflow not published | Publish it; check the Production URL |
| Publish greyed out | Unsaved changes, invalid node, or a duplicate workflow | Ctrl+S; check red triangles; delete duplicates |
| `The column "" could not be found` | A Sheets node was hand-edited | Re-import; do not touch Document/Sheet fields |
| Empty `200` response | A branch ended without a Respond node | Re-import — every branch needs one |
| Sheet dropdown won't populate | Credential not truly connected | Re-do the OAuth sign-in, allow popups |
| Rows append blank | Sheet headers changed | Must match `data/Claims-Template.csv` exactly |
| Agent says "can't find your policy" for a good number | Workflow A down | Check Executions; the flow now says "trouble with our records" instead |
