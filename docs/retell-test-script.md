# Retell Test Script

Scripted conversations for testing ClaimLine AI in Retell's Playground, with
the exact thing to check after each turn.

**Use text mode, not audio.** Retell dashboard → **Agents** → **ClaimLine AI** →
**Test** → text. Text mode costs almost nothing, and — the real reason — it
shows every function call with its full **request** and **response** payload in
the side panel. Audio hides all of that. Switch to audio only at the end, to
check how it *sounds*.

> **The single most useful habit:** after every agent reply that involved a
> function, expand that call in the side panel and read the **response**. The
> flow branches on `result`, so that one field predicts everything the agent
> does next. If the agent surprises you, the response almost always explains it.

---

## Test 1 — Knowledge Base only (no backend involved)

Run this first. It isolates Retell from n8n and Google entirely, so if it works
you know the agent, prompt and knowledge base are sound.

| You say | Expected |
|---|---|
| `What does my home policy cover?` | Fire, theft, flood, structural damage |
| `What documents do I need for a health claim?` | Discharge summary + itemised bills. **Only health** — not all four types |
| `How long does a claim take?` | 5–7 business days standard, 24–48h urgent |
| `What does "under review" mean?` | A handler is actively assessing it |
| `How much is my premium?` | Politely declines — it is not in the knowledge base |

**Pass:** no function calls at all in the side panel. Answers match
`docs/ClaimLine-Policy-FAQ.docx`.

**That last question matters most.** The agent must refuse rather than invent a
number. A voice agent that makes up a premium is worse than one that says "I
can't confirm that."

---

## Test 2 — File a claim (the full happy path)

Send these **one at a time**, waiting for the reply each time.

```
1.  I need to file a claim
2.  POL-10234
3.  Yes that's me
4.  Someone reversed into my car in a car park
5.  Yesterday
6.  I was parked and a van backed into my door. Nobody was hurt, just a big dent.
7.  Sara Ahmed
8.  sara.test@example.com
9.  Yes, please file it
```

### What must happen at each step

| After | Expect | Check in the side panel |
|---|---|---|
| 2 | Agent says **"Sara Ahmed"** and **"Auto"** cover | `validate_policy` → `result: "valid"` |
| 4 | Asks *when* — one question only | no call |
| 5 | Converts to a real date | no call |
| 6 | Asks name or email next | no call |
| 8 | Reads the email back for confirmation | no call |
| 9 | **Reads a claim ID back TWICE**, digit by digit, mentions 5–7 business days | `create_claim` → `result: "standard"`, a `claim_id` |

**Pass:** a `CLM-xxxxxx` ID spoken twice, and a new row in your Google Sheet's
**Claims** tab with urgency `Standard`.

---

## Test 3 — Urgency triage (the headline feature)

Same as Test 2, but replace step 6 with:

```
I was rear-ended at a red light and my wife was taken to hospital by ambulance
```

| Expect | Why |
|---|---|
| `create_claim` response has `result: "urgent"` and `urgency: "Urgent"` | n8n re-read the description server-side |
| Agent says **24 to 48 hours**, not 5–7 days | it took the urgent branch |
| Agent briefly acknowledges the injury before continuing | the empathy rule in the global prompt |
| Sheet row shows `Urgent` | the authoritative value was stored |

**The interesting part:** open the `create_claim` **request** too. The agent
sent `"urgency": "Standard"` or `"Urgent"` — its own guess — and the
**response** came back `"Urgent"` regardless, because n8n found *hospital* and
*ambulance* in the description. That override is the point: urgency drives a
real SLA, so it is decided by a rule that always gives the same answer, not by
a model that might not.

---

## Test 4 — Invalid policy (must never file)

```
1.  I want to file a claim
2.  POL-99999
```

| Expect | Must NOT happen |
|---|---|
| `validate_policy` → `result: "not_found"` | Never calls `create_claim` |
| Agent reads the digits back and offers one retry | Never invents a policyholder name |
| After a second failure, offers the claims team | Never loops a third time |

Then give it `POL-10234` at the retry and confirm it recovers and continues
normally.

**Why this is the most important test:** in a single-prompt agent, "validate
before filing" is a polite instruction the model can skip when a caller is
insistent. Here it is the graph — `create_claim` is only reachable through the
`result == "valid"` edge. This test proves the structure, not the wording.

---

## Test 5 — Check status

```
Can you check claim CLM-000001?
```

Expect `check_status` → `result: "found"`, and the agent reads back the status
plus what it means.

Then a fake one:

```
Can you check claim CLM-999999?
```

Expect `result: "not_found"`, a digit-by-digit read-back, one retry offer, and
**no invented status**.

---

## Test 6 — Fuzzy input (voice realism)

Speech-to-text mangles identifiers constantly. All of these must resolve to the
same policy:

```
my policy number is POL-10234
pol 10234
10234
P O L one zero two three four
P-O-L one oh two three four
```

All should return `holder_name: "Sara Ahmed"`. The repair happens server-side in
n8n's Normalize node, so the agent never has to hear perfectly.

Same for claim IDs — these all mean `CLM-000042`:

```
CLM-000042
claim 42
C L M zero zero zero zero four two
```

---

## Test 7 — Post-call (after hanging up)

End a call in which you **did** file a claim, then wait ~60 seconds for Retell's
post-call analysis.

1. **Retell → Call History** → open the call → **Analysis** tab. Confirm the
   extracted fields: `claim_filed: true`, a `claim_id`, `urgency`, `name`,
   `email`
2. **n8n → Executions** → Workflow B ran, all nodes green
3. **Your inbox** → confirmation email with the right claim ID
4. **Google Sheet → Analytics** → new row
5. **https://claimline-ai.streamlit.app** → **Refresh data** → the claim appears

Then end a call where you only **asked a question**. Expect
`claim_filed: false`, **no email**, but an Analytics row logging the call.

---

# If filing a claim is not working

Work down this list — each step tells you which side of the system is at fault.

## Step 1 — which function actually got called?

Open the side panel and look for the function calls in order. What you see
tells you where it stopped:

| Symptom | Meaning | Where to look |
|---|---|---|
| No `validate_policy` at all | The flow never left the greeting/intent node | Retell — intent routing |
| `validate_policy` ran, no `create_claim` | It stalled while collecting details | Retell — the collection node |
| `create_claim` ran but errored | Backend | n8n Executions |
| `create_claim` succeeded, no sheet row | Backend | n8n → Append Claim Row output |

## Step 2 — read the `create_claim` REQUEST

Expand the call and check the arguments the agent sent. Every one of these is
required; if any is missing or malformed, the call fails:

```json
{
  "action": "create_claim",
  "policy_number": "POL-10234",
  "holder_name": "Sara Ahmed",
  "incident_type": "Accident",
  "incident_date": "2026-08-05",
  "description": "...",
  "email": "sara.test@example.com",
  "urgency": "Standard"
}
```

Most common problems, in order:

- **`incident_date` not `YYYY-MM-DD`.** The caller said "yesterday" and the
  agent passed "yesterday" through. It must convert.
- **`incident_type` not one of the seven allowed values** (`Accident`, `Theft`,
  `Fire`, `Flood`, `Medical`, `Damage`, `Other`). Anything else is rejected,
  because the parameter is a strict enum.
- **`email` missing.** The agent moved on before getting one.
- **`description` sanitised.** Not a failure, but if the agent summarised
  "taken to hospital" into "a road traffic incident", the urgency keywords are
  gone and a genuinely urgent claim gets a 5–7 day SLA.

## Step 3 — if the agent asks the same question twice, or never files

That is the collection node not recognising it has everything. Say explicitly:

```
Yes, that's all correct, please file the claim now
```

If that unblocks it, the node needed a clearer completion signal, and the fix
is in the flow rather than anything you did wrong.

## Step 4 — if the agent says "I'm having trouble pulling up our records"

That is the flow's **honest backend-failure message**, not a not-found. It
means the webhook did not answer. Note that it deliberately does **not** say
"policy not found" — so you know the number was fine and the problem is the
connection. Go to n8n → **Executions** and open the most recent run.

## Step 5 — collect this before asking for help

Whatever happens, capture these four things — together they identify almost any
failure without guesswork:

1. The **transcript** from the point the claim started
2. The `create_claim` **request** payload
3. The `create_claim` **response** payload (or the fact that no call was made)
4. The matching **n8n execution** — which node is red, and its error text
