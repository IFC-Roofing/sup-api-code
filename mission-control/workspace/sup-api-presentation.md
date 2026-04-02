# Sup AI — How We're Connecting It to the IFC App

---

## The Problem

Right now, our supplement work lives in two separate worlds:

- **The IFC app** — where the team manages projects, flow cards, conversations, and tracks everything
- **The Sup AI tools** — where we generate supplement PDFs, markup bids, build call scripts, and run QA reviews

The team has to jump between both. There's no bridge. When a rep wants to generate a supplement, they can't just ask for it inside the app — they have to go through a separate process.

---

## What We Built

We created a **small service** that sits between the IFC app and our supplement tools. Think of it like a translator.

The IFC app says: *"Hey, generate a supplement for Rose Brock."*

The service takes that request, runs our full pipeline (pulls the files, builds the estimate, generates the PDF, uploads it to Drive), and sends back the results — the Drive link, the dollar amounts, the trade breakdown — all formatted so the IFC app can display it right there in the supplement tab.

**The rep never leaves the app.** They ask, they wait a few minutes, they get their supplement. Same quality, same pipeline, zero context switching.

---

## How It Works (Simple Version)

```
Sales rep types in the supplement tab
        ↓
IFC app sends a request to our service
        ↓
Our service runs the supplement pipeline
        ↓
PDF gets generated and uploaded to Drive
        ↓
Results come back to the app
        ↓
Rep sees the Drive link, RCV total, and trade breakdown
```

No new logins. No new tools to learn. No new tabs to open. It just works inside what the team already uses every day.

---

## What's Available

We didn't just connect one tool — we connected five:

| What the rep asks for | What happens behind the scenes |
|---|---|
| "Generate a supplement" | Full PDF pipeline — estimate, render, upload to Drive |
| "Run a bid markup" | Compares sub bids to Xactimate pricing, flags issues |
| "Build me a pre-call script" | Pulls all project context and builds a call prep guide |
| "Give me a calling script" | Builds a structured phone script for the adjuster call |
| "Review this supplement" | QA check — verifies bids, measurements, photos, F9s |

All five work from the supplement tab. The rep just asks in plain English.

---

## What Doesn't Change

- **The IFC app stays exactly the same.** We're not modifying how it works — we're adding capability to it.
- **The supplement pipeline stays the same.** Same tools, same quality, same output. We just made it callable from the app.
- **No new infrastructure to manage.** The service is lightweight — it costs less than a Netflix subscription to run on a small server.
- **Security.** Every request requires authentication. The service only responds to the IFC app, nobody else.

---

## What We Need From the Team

1. **Review the code** — 5 small Ruby files that tell the IFC app how to talk to our service, plus a setup script
2. **Two environment variables** — a URL (where our service lives) and a key (for authentication)
3. **Approval to merge** — once reviewed, it's a one-time setup

After that, it's live. No ongoing maintenance needed from the IFC dev team.

---

## What's Next (If This Goes Well)

- **Smarter over time** — The system can learn from every supplement decision (what trades get approved, what carriers fight on, what works) and feed those lessons back to every rep automatically
- **Faster repeat work** — Caching so back-to-back requests on the same project don't start from scratch every time
- **More skills** — Response analysis, reinspection strategy, appraisal prep — all accessible from the same tab

---

## The Bottom Line

We're not replacing anything. We're connecting what already works — on both sides — so the team can do supplement work without leaving the tool they already live in.

One tab. One conversation. Full pipeline.
