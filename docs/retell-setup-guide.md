# Retell AI — Complete Setup Guide (ClaimLine AI)

A click-by-click walkthrough of building the ClaimLine AI agent in the Retell
dashboard. Written for someone who has never used Retell's Conversation Flow
builder before. Every step says **what** to click and **why it matters** — the
"why" is the part that saves you when the UI moves.

**Time:** about 60–75 minutes end to end.

---

## Before you start — build order matters

Retell needs URLs that only exist once n8n is running, and n8n needs a Google
Sheet that only exists once you've made it. Working in this order avoids
backtracking:

| # | Do this first | Why Retell needs it |
|---|---|---|
| 1 | Create the `ClaimLine-Data` Google Sheet with the three tabs | n8n writes to it |
| 2 | Import Workflow A into n8n, set the Sheet ID, **Publish**, copy its Production URL | The three Retell functions POST to it |
| 3 | Import Workflow B into n8n, **Publish**, copy its Production URL | Retell's post-call webhook targets it |
| 4 | Then everything below | |

> **The n8n trap that costs everyone an hour:** every n8n webhook node has a
> **Test URL** (`/webhook-test/...`) and a **Production URL** (`/webhook/...`).
> The Test URL only responds while you're sitting in the editor with "Listen for
> test event" armed, and it accepts exactly one request before going dead. Put a
> Test URL into Retell and your agent will work perfectly once and then never
> again. **Always paste the Production URL** (`/webhook/`, no `-test`), and make
> sure the workflow is **Published**.

You'll need these three values as you go. Fill them in here:

```
Workflow A production URL:  https://______.app.n8n.cloud/webhook/claimline-action
Workflow B production URL:  https://______.app.n8n.cloud/webhook/claimline-post-call
Google Sheet ID:            ____________________________________
```

---

## Step 1 — Create your Retell account

1. Go to **https://retellai.com** and sign up. The free trial credits are enough
   for this entire build plus a few dozen test calls.
2. You land on the dashboard. The left sidebar is your whole world here:
   **Agents**, **Knowledge Base**, **Phone Numbers**, **Call History**,
   **API Keys**.

**Cost note:** test calls burn trial credits by the minute. Use the text-based
test mode (Step 8) for logic testing and save voice calls for verifying that the
agent actually *sounds* right — it's roughly 10× cheaper in credits.

---

## Step 2 — Create the Knowledge Base *first*

Do this before creating the agent, so the agent can be attached to it at
creation time instead of you having to go back and edit it.

1. Sidebar → **Knowledge Base** → **Add Knowledge Base**.
2. Name it `ClaimLine Policy FAQ`.
3. Choose **Upload Files** and upload `docs/ClaimLine-Policy-FAQ.docx` from this
   repo.
4. Save, and **wait for the status to read Ready / Complete.** Retell has to
   chunk the document and generate embeddings; if you attach it while it's still
   processing, the agent will answer "I don't have that information" to
   everything and you'll waste twenty minutes debugging a prompt that was never
   the problem.

**What a Knowledge Base actually does:** at conversation time Retell embeds the
caller's question, retrieves the most similar chunks from your document, and
injects those chunks into the model's context. It is retrieval, not memorisation
— which is exactly why the agent can't invent a coverage limit that isn't in the
document, and why the doc's wording matters. Keeping facts here rather than in
the prompt means updating a policy is a document re-upload, not a prompt rewrite.

---

## Step 3 — Create the agent (Conversation Flow, not Single Prompt)

1. Sidebar → **Agents** → **Create an Agent**.
2. You'll be offered agent types. Choose **Conversation Flow**.
3. Name it `ClaimLine AI`.

**Why Conversation Flow and not Single Prompt** (this is the whole point of the
project — worth being able to explain in an interview):

| | Single Prompt | Conversation Flow |
|---|---|---|
| Structure | One big prompt; the LLM decides what to do next each turn | A graph of nodes with explicit edges |
| Branching | "Please remember to check the policy first" — a request, not a rule | An edge that physically cannot be skipped |
| Predictability | Same input can take a different route on different runs | Same input, same route |
| Debugging | "Why did it do that?" — read the transcript and guess | Look at which node it was in |

For ClaimLine specifically: a claim must **never** be created before the policy
is validated. In a Single Prompt agent that's a polite instruction the model can
skip when a caller is insistent. In a Conversation Flow it's the graph — the
`create_claim` node is only reachable through the `valid == true` edge.

---

## Step 4 — Global settings

Open the agent. The right-hand settings panel is where these live.

### Voice
Pick a neutral, professional voice. **Test it on the word "claim" and on a
digit string** before committing — some voices slur digit sequences, which is
fatal for an agent whose whole job is reading claim IDs aloud.

### Model
Use the default (or the fastest available "realtime"-class model). Voice quality
is dominated by *latency*, not by model size — a 300 ms pause before every reply
feels far worse to a caller than a slightly less eloquent sentence.

### Global Prompt
Paste **PART 1** of `prompts/conductor-prompt.txt` here. Every node inherits it,
so persona, style, the "never invent a figure" rule, and the digit-reading rules
apply everywhere without being repeated per node.

### Knowledge Base
Attach `ClaimLine Policy FAQ` from Step 2.

### Settings worth changing from default

| Setting | Set to | Why |
|---|---|---|
| **Interruption sensitivity** | Slightly below default | The agent reads claim IDs aloud. At high sensitivity a caller's "mm-hm" cuts it off mid-ID and they never hear the full number. |
| **Backchannel** ("mm-hm", "I see") | **On** | Callers describing a car crash talk for 20+ seconds. Total silence makes them stop to ask "hello?" |
| **Responsiveness / latency** | Toward faster | Dead air after "what's your policy number" reads as a broken line. |
| **Max call duration** | 10 minutes | A stuck loop shouldn't be able to burn your trial credits overnight. |
| **Voicemail detection** | On | Stops the agent cheerfully filing a claim into an answering machine. |
| **Begin message** | Agent speaks first | A voice agent that waits silently for the caller to speak first gets hung up on. |

---

## Step 5 — Build the flow with Conductor

**What Conductor is:** an AI copilot inside the flow editor that turns a plain
English description into actual nodes, edges and function definitions. You
describe the flow; it builds the graph. Much faster than dragging twelve nodes
into place, and (more importantly) it wires the edges the way you described them
rather than the way you got tired of clicking.

1. Open your agent → the flow canvas.
2. Find the **Conductor** panel (an AI/chat/sparkle icon on the canvas — Retell
   moves it between the left rail and a floating button; it's the one that asks
   what you want to build).
3. Open `prompts/conductor-prompt.txt`, **copy the whole file**, paste it in,
   and send.
4. Give it a minute. It'll produce roughly a dozen nodes: the greeting, the
   three-way router, the Path A / B / C chains, the shared handoff and end nodes.

### Then review what it built — always

Conductor is a scaffolder, not an oracle. Walk the canvas and check:

- [ ] The greeting node has **four** outgoing edges (Q&A, file, status, unclear).
- [ ] `N2e` (create claim) is reachable **only** through the `valid == true`
      edge from `N2a`. If Conductor drew a shortcut from `N2` straight to `N2e`,
      delete it — that edge lets a claim be filed against a policy that was
      never checked, which defeats the entire design.
- [ ] The urgent path `N2g` exists and branches off the **create_claim
      response**, not off anything the agent guessed earlier.
- [ ] Both retry loops (`N2b → N2a`, `N3c → N3a`) exist.
- [ ] Every path terminates at an **Ending node**. A node with no outgoing edge
      that isn't an Ending node = a call that hangs in silence.

**Iterating:** you don't have to re-paste the whole brief. Ask Conductor for
targeted changes: *"On the claim-not-found node, add an edge back to the check
status function so the caller can retry once."*

---

## Step 6 — Wire the three custom functions

This is the part Conductor most often gets *structurally* right and *detail*
wrong, so verify each one by hand.

Open each **Function node** on the canvas. For each of `validate_policy`,
`create_claim`, `check_status`:

1. **Name** — must match **exactly**: `validate_policy`, `create_claim`,
   `check_status`. Lowercase, underscores.
2. **URL** — your **Workflow A production URL**, for all three. Yes, the same
   URL three times.
3. **Method** — `POST`.
4. **Parameters** — the JSON schema from PART 2 of the brief.
5. **Speak During Execution** — **ON**, with the filler line from the brief
   ("Let me pull that policy up"). This is not cosmetic: the round trip to n8n
   and Google Sheets takes 1–3 seconds, and 3 seconds of silence on a phone call
   is long enough that callers say "hello? are you there?" and talk over the
   agent's answer.
6. **Speak After Execution** — **OFF**. The next conversation node does the
   talking, and it can phrase things based on which branch was taken.
7. **Timeout** — 15 seconds.

### Why one URL and three functions

All three POST to the same n8n webhook and are distinguished by an `action`
field that the schema pins with `enum` — `["validate_policy"]` is a
single-value enum, so the model cannot send anything else. One webhook means
one workflow to publish, one URL to update, and one execution log to read when
something breaks. n8n's Switch node does the routing.

### The critical detail on `create_claim`

The `description` parameter must be captured close to **verbatim**. The n8n
Code node runs a keyword rule over that text to decide Urgent vs Standard. If
the agent politely summarises "my wife was taken to hospital by ambulance" down
to "a road traffic incident occurred", the keywords are gone and a genuinely
urgent claim gets a 5–7 day SLA. The parameter description in the brief tells
the model this explicitly — keep that wording.

---

## Step 7 — Test in the Playground (before any of the deployment steps)

The **Test** panel gives you two modes:

- **Test LLM / text mode** — type instead of talking. Fast, cheap, and it shows
  you every function call with its exact request and response payload. Use this
  for *all* logic testing.
- **Test Audio** — a real voice call. Use this only to check pacing, voice
  quality and whether digit strings are intelligible.

Run all six acceptance tests from **PART 6** of the brief. For each, verify in
the Playground's side panel:

| Test | What to verify |
|---|---|
| Policy question | **No** function call fires; the answer matches the FAQ doc |
| Valid policy claim (POL-10234) | `validate_policy` returns `valid: true`, name is "Sara Ahmed"; a new row appears in the Claims tab |
| Invalid policy (POL-99999) | `valid: false`; agent offers one retry; never reaches `create_claim` |
| Injury description | `create_claim` **response** shows `"urgency": "Urgent"`; agent takes the urgent branch |
| Real claim ID | `found: true`, correct status read back |
| Fake claim ID | `found: false`, graceful retry, no invented claim |

Cross-check every claim test against the **Claims tab** in Google Sheets and the
**Executions** tab in n8n. Three places must agree: the transcript, the n8n
execution, and the sheet row.

---

## Step 8 — Post-Call Data Extraction

Find **Post-Call Analysis** (sometimes **Analysis** / **Post-Call Data**) in the
agent settings.

**What it is:** after the call ends, Retell runs a *second* LLM pass over the
full transcript and extracts the structured fields you define. It's separate
from the live conversation — the agent isn't filling a form during the call, an
analyser reads the transcript afterwards.

**Why it exists:** it's the clean seam between "a conversation happened" and
"a record exists". Your post-call automation gets typed fields instead of having
to parse a transcript.

Add the five fields from **PART 4** of the brief:

| Field | Type | Gotcha |
|---|---|---|
| `claim_filed` | Boolean | Must be false for status-check calls. Workflow B's IF node keys on this — get it wrong and callers who only checked a status get a "your claim has been filed" email. |
| `claim_id` | Text | Empty for status checks. A caller *checking* CLM-000001 did not *create* it. |
| `urgency` | Text | Exactly `Standard`, `Urgent`, or `n/a` |
| `name` | Text | Empty if no claim filed |
| `email` | Text | Lowercase. This is the send-to address — an empty field is far better than a guessed spelling |

The **description text you write for each field is the prompt** the analyser
runs on. Vague descriptions produce vague extractions. Use the wording from the
brief verbatim — it's written to close the specific failure modes above.

---

## Step 9 — The post-call webhook

Find **Webhook Settings** in the agent settings.

1. Paste your **Workflow B production URL**.
2. Enable **only** the `call_analyzed` event.

**Why only that one event.** Retell fires three:

| Event | When | Are the extracted fields ready? |
|---|---|---|
| `call_started` | Call connects | No — call hasn't happened |
| `call_ended` | Caller hangs up | **No** — analysis hasn't run yet |
| `call_analyzed` | Post-call analysis completes | **Yes** |

`call_ended` is the trap: it fires and looks like the right moment, but
`custom_analysis_data` is still empty. Workflow B would run green, email nobody,
and log a blank analytics row. Enable `call_analyzed` only.

**Test it before moving on:** in n8n, open Workflow B, click **Listen for test
event**, make one test call in Retell, and confirm an execution arrives with
`call.call_analysis.custom_analysis_data` populated. If it's empty, you're on
the wrong event.

---

## Step 10 — Publish the agent

Retell versions agents. Editing the canvas changes the **draft**; the version
your widget and phone numbers serve is the **published** one.

1. Click **Publish** (top right).
2. Note the version number.

Edit later and you must Publish again. "I fixed it but the live agent still does
the old thing" is nearly always an unpublished draft.

---

## Step 11 — Get the widget credentials for the dashboard

You need two values: the **agent ID** and a **public key**. The agent ID already
exists; the public key you have to create.

### 11a. Agent ID
On the agent page, click the **ID** control next to *Agent details* (bottom-left
of the canvas) and copy it. It starts with `agent_`.

### 11b. Public key — you MINT this, it does not already exist

This is account-level, not per-agent, so it is **not** on the agent page and
**not** behind the agent's *Share* button (Share gives you a hosted voice-orb /
preview link, which is a different thing — see 11c).

1. Go to **Settings → API Keys**.
2. Select the **Public Keys** tab (next to *API Keys*).
3. **+ Add Key**, and fill the dialog in:

| Field | Value | Why |
|---|---|---|
| Key Name | `ClaimLine-Streamlit-Widget` | A label for you |
| Allowed Domains | your Streamlit domain, e.g. `claimline-ai.streamlit.app` | Restricts where the key works. Leave empty while developing, then lock it down after deploying. |
| Abuse Prevention (reCAPTCHA) | **OFF** | Turning this on makes the key demand a reCAPTCHA token that the frontend must supply. `streamlit_app.py` does not send one, so the call button would fail authentication every time. |
| Fraud Protection | OFF | IP-based request limiting. Fine off for a demo; on, it can flag your own repeated test calls. |

4. **Save**, then copy the value from the **Key Value** column. It starts with
   `public_key_`.
5. Put both values into Streamlit secrets (see
   `.streamlit/secrets.toml.example`).

**On Allowed Domains.** The public key is visible in your page source by design,
so an empty allowlist means anyone can copy it and embed your agent on their own
site, spending your credits. Restricting it to your own domain closes that. The
tradeoff is that a wrong entry blocks your own app with an opaque failure — so
get the widget working with it empty, then add the domain once you know your
deployed URL.

### 11c. Bonus — the hosted preview link

The agent's **Share** button offers a *Voice Orb* shareable link and a *Preview
link* once **Public access** is toggled on:

```
https://agent.retellai.com/preview/<your-agent-id>
```

That is a working, no-code public demo you can share immediately — useful as a
backup link in your README if the Streamlit app hibernates. It does not replace
the widget (it is Retell-hosted, not embedded in your dashboard), but it is free
and it works before anything else is deployed.

### Public key vs private API key — get this right

The *public* key is designed to be visible in page source; it can only start a
web call with the agent you name and nothing else. That is why the dashboard
needs no backend token server. Your Retell **private API key** (the `key_…` one,
on the *API Keys* tab) can create agents, read every transcript and spend your
credits — it must never appear in this repo, in Streamlit secrets, or in any
client-side code.

---

## Step 12 — Optional: a phone number

Sidebar → **Phone Numbers** → buy or import one, and assign it to the ClaimLine
AI agent. Not required — the website widget is enough for the demo, and it keeps
the whole build inside the free tier.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Agent worked once, then function calls fail | You used the n8n **Test URL** | Swap to the Production URL (`/webhook/`, no `-test`) and Publish the workflow |
| "I don't have that information" for everything | Knowledge Base still processing, or not attached | Check status is Ready, confirm it's attached to the agent |
| Long silence before every answer | Speak During Execution is off | Turn it on for all three function nodes |
| Claim row appears with blank columns | Sheets column headers don't match | Header row must be exactly the columns in `data/Claims-Template.csv`, spelled identically |
| Injury claim triaged Standard | Agent summarised the description | Re-check the `description` parameter wording; confirm the raw text in the n8n execution |
| Confirmation email never arrives | Wrong webhook event, or `claim_filed` extracted as false | Verify `call_analyzed` only; open the n8n Workflow B execution and inspect the Flatten node's output |
| Status-check callers get "claim filed" emails | `claim_filed` extracted as true on a lookup call | Tighten the `claim_filed` field description; it must say *newly created this call* |
| Widget shows but the call button does nothing | Microphone blocked | Widget needs HTTPS + mic permission; check the browser's site permissions |
| Edits don't take effect on the live widget | Agent not re-published | Publish again |

---

## What "done" looks like

- [ ] Knowledge Base uploaded, status Ready, attached to the agent
- [ ] Conversation Flow built, all six acceptance tests pass in the Playground
- [ ] Three custom functions pointing at Workflow A's **production** URL
- [ ] Five post-call extraction fields configured
- [ ] Webhook set to Workflow B, **`call_analyzed` only**
- [ ] Agent **published**
- [ ] Public key + agent ID copied into Streamlit secrets
- [ ] One real end-to-end call: claim ID spoken → row in Sheets → n8n execution
      green → confirmation email received → row visible on the dashboard
