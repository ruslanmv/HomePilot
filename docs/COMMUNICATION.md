# COMMUNICATION.md — how HomePilot personas and you stay in touch

**Audience.** Users who want to call their persona (or be called by
it) over real phone, WhatsApp, or Telegram.

**Scope.** The basics. For the per-turn conversation physics of a
live voice call see [docs/PHONE.md](./PHONE.md); for provider-specific
wizard setup see **Projects → MCP Servers → Manage → Communication**
inside the app.

Two directions, three channels. Everything below is **opt-in and
off by default** — nothing changes about the in-app chat or
browser-call experience until you install a connector and flip the
switches.

---

## 1. The two directions

```
  YOU  ─────────── 📞 call ───────────►  PERSONA
       ─────────── ✍️ message ─────────►
                                           │
                                           │ (recurrent checks,
                                           │  incidents, reminders)
                                           ▼
  YOU  ◄────────── 📞 call ─────────── PERSONA
       ◄────────── ✍️ message ────────
```

| Direction | What the user does | What the persona does |
|---|---|---|
| **You → AI** | Dial your app's phone number · send a WhatsApp/Telegram message | Answers "live" — full-duplex voice turn-taking for calls, contextual reply for messages |
| **AI → You** | Nothing; you just receive | Persona initiates on its own (e.g. secretary: *"door-left-open alert, want me to arm the alarm?"*) — message first, escalation call if unacknowledged |

Industry equivalent: a secretary with a desk phone + a WhatsApp and
Telegram account. Not a contact-center.

---

## 2. The three channels

| Channel | Provider class | What arrives on your device | Typical use |
|---|---|---|---|
| 📞 **Phone (PSTN)** | Twilio / Telnyx / Infobip | A real phone call to your mobile | Urgent alerts, live problem-solving |
| 💬 **WhatsApp** | Meta Cloud API | A WhatsApp message from the persona's business number | Reminders, quick ACK/SNOOZE/ESCALATE replies |
| ✈️ **Telegram** | Telegram Bot API | A message from your persona's bot | Lower-friction alerts + voice notes |

All three are implemented as **MCP servers** — independent processes
that plug into HomePilot's gateway. Installing or removing any one
doesn't touch the others or any core feature.

---

## 3. The five pieces that make it work

```
 ┌────────────────┐   ┌────────────────────┐   ┌──────────────────┐
 │ Your reachability│  │ Provider connector │   │ MCP tool surface │
 │  (Profile tab)  │  │  (Meta / Twilio /  │   │  hp.whatsapp.*   │
 │                 │  │   Telegram / Bot)  │   │  hp.telegram.*   │
 └────────┬────────┘  └──────────┬─────────┘   │  hp.voip.*       │
          │                      │             └────────┬─────────┘
          │     ┌────────────────┴────────┐             │
          └────►│ Persona policy (allow-  │◄────────────┘
                │  list + access tiers)   │
                └───────────┬─────────────┘
                            │
                            ▼
                   ┌─────────────────┐
                   │ voice_call /    │
                   │ chat pipeline   │
                   └─────────────────┘
```

1. **Your reachability** — `Profile → Communication` tab stores your
   phone number, WhatsApp number, and Telegram username *plus* a
   per-field access tier (always / on demand / sensitive). None of
   this is a secret; it's where the persona should reach you.
2. **Provider connector** — installed once per channel via
   `Projects → MCP Servers → Manage → Communication`. The wizard
   walks through tokens, webhook URLs, and the single phone number
   this app instance answers on.
3. **MCP tools** — the connector exposes `hp.whatsapp.send_message`,
   `hp.telegram.send_message`, `hp.voip.call.create`, etc. Personas
   call these like any other tool.
4. **Persona policy** — per-persona allowlist decides *which*
   channels a persona can touch. By default only `secretary` can
   send outbound; `analyst` is read-only.
5. **voice_call / chat pipeline** — inbound calls flow through the
   ingress bridge into the existing browser-call WebSocket, so the
   persona's behaviour on the phone is identical to its behaviour
   in the app.

---

## 4. "You call the persona" — the inbound path

### Setup

1. Install the VoIP MCP server (`hp-voip`, port 9132). Wizard asks for
   your Twilio/Telnyx account + the **one** phone number this app
   instance owns (single-DID mode).
2. Create a DID route with `hp.voip.did_route.upsert`:
   `did_e164=+14155551212 → persona_id=secretary`.
3. Point your provider's inbound webhook at HomePilot.
4. Flip `TELEPHONY_ENABLED=true` on the server + `WRITE_ENABLED=true`.

### What happens when you dial

```
  You dial +1-415-555-1212
           │
           ▼
  Provider (Twilio) sends webhook
           │   (HMAC-SHA1 signature verified)
           ▼
  hp.voip.ingress.route_call  →  "accept, persona=secretary"
           │
           ▼
  ingress_bridge.py   →   voice_call.create_session(persona_id=...)
           │
           ▼
  Persona's standard opening plays ("Hello, Secretary here…")
           │
           ▼
  Live full-duplex voice conversation — turn-taking, barge-in,
  structured [call] telemetry, exactly like the browser call
```

Under the hood the **same** `voice_call` pipeline drives it — that
means the full-duplex guardrails from PHONE.md (turn-lock, post-TTS
echo margin, shared TTS ownership) apply identically on a real
phone line.

---

## 5. "The persona calls you" — the outbound path

### Two sub-cases

**Message-first escalation** (recommended — polite):
```
  Secretary detects an incident
           │
           ▼
  hp.voip.incident.trigger    → audit entry
           │
           ▼
  hp.whatsapp.send_message(to=your_whatsapp, text="...")
           │
           │ 60 s wait for ACK/SNOOZE
           ▼
  No response?
           │
           ▼
  hp.voip.call.create(to=your_phone, prompt="I'm calling because…")
```

**Direct call** (only with your `allow_ai_outbound` toggle on):
```
  Secretary decides to call immediately
           │
           ▼
  hp.voip.call.create(to=your_phone, consent_granted=true)
           │
           ▼
  Persona speaks via TTS; you press 1 (ACK) / 2 (snooze) / 3 (escalate)
```

### The consent wall

Every outbound tool (`hp.*.send_message`, `hp.voip.call.create`)
requires `consent_granted=true` in the arguments. Personas set this
only when:

- **Profile → Communication → Allow the AI to contact me without
  confirmation** is ON, OR
- The user has clicked the in-app confirmation prompt for that
  specific turn.

Otherwise the tool returns a `blocked: no-consent` string and the
persona asks first.

---

## 6. Access tiers — how the AI knows whether it may use a number

Every field in `Profile → Communication` carries an AI-access tier:

| Tier | Green | Amber | Rose |
|---|---|---|---|
| **Always available** | Fine | — | — |
| **On demand** | — | Persona can ask *"may I use your WhatsApp?"* | — |
| **Sensitive — ask first** | — | — | Single-click confirmation required for every use |

Defaults:

- **Phone / WhatsApp / Telegram**: `sensitive` (safe default)
- **Preferred contact / call channel**: `on_demand`

You change these on the Communication tab — the pill next to each
field flips between the three tiers.

---

## 7. Minimum viable setup (20 minutes)

The fastest "working persona on the phone" recipe:

1. **Buy a Twilio phone number** (~$1/month).
2. **Install hp-voip** via the MCP Manager wizard. Paste the Twilio
   SID + Auth Token; set VOIP_APP_DID to the number you just bought;
   set the provider's "A call comes in" webhook to your HomePilot
   URL.
3. **Upsert a route**:
   ```
   hp.voip.did_route.upsert(
     did_e164="+14155551212",
     persona_id="secretary",
   )
   ```
4. **Fill Profile → Communication** with your mobile number (for the
   outbound direction).
5. **Flip both toggles** on the VoIP server: `TELEPHONY_ENABLED=true`,
   `WRITE_ENABLED=true`.
6. Dial your new number. Secretary picks up.

For WhatsApp: install hp-whatsapp, run through the Meta Cloud API
wizard (~15 extra minutes). For Telegram: install hp-telegram, talk
to @BotFather (~5 minutes).

---

## 8. Safety guarantees

- **Install states**: every MCP server ships `INSTALLED_DISABLED` by
  default. Tools return "unavailable" until you flip `INSTALL_STATE=ENABLED`.
- **Dry-run by default**: `WRITE_ENABLED=false` means no real message
  or call ever fires — the tool returns a preview string. Set this
  to `true` only when you've tested the connector.
- **Webhook signature verification**: `hp.voip.webhook.verify` (HMAC),
  `hp.whatsapp.webhook.verify` (X-Hub-Signature-256),
  `hp.telegram.webhook.verify` (secret-token). Spoofed callbacks are
  rejected at the edge before they reach the persona.
- **Single-DID policy**: the VoIP server accepts inbound calls only
  on `VOIP_APP_DID`. One app instance = one phone number. Caller
  spoofing a different DID gets a silent reject.
- **Persona allowlist**: `VOIP_PERSONA_ALLOWLIST` / `WHATSAPP_PERSONA_ALLOWLIST`
  / `TELEGRAM_PERSONA_ALLOWLIST` decide which personas can invoke
  which tools. An `analyst` persona with no entry can't call tools.
- **Audit trail**: every outbound + every ingress decision lands in
  the server's audit ring buffer, fetchable via `hp.*.audit.list`.

---

## 9. Concrete scenarios

### Scenario A — you call your secretary

> You dial +1-415-555-1212. Secretary picks up: *"Hello, this is Nova."*
> You: *"Any messages?"* She reads the 3 unanswered WhatsApps from
> your family and offers to reply. You hang up. The persona logs the
> call in the conversation history.

### Scenario B — secretary detects a problem

> At 22:47 a smart-home MCP tool reports the front door has been
> open for 10 minutes. Secretary raises `hp.voip.incident.trigger`
> → sends WhatsApp *"The front door is open. Reply ACK to confirm
> or SNOOZE 10m."* You reply ACK from the couch. No escalation.

### Scenario C — secretary can't reach you

> Same incident, but you're asleep. No WhatsApp reply after 60 s.
> Policy escalates to `hp.voip.call.create`. Your phone rings.
> Persona: *"Front door open, I can't reach you on WhatsApp.
> Press 1 to acknowledge, 2 to snooze, 3 to escalate."* You press 1.
> Persona confirms and logs.

---

## 10. What this is *not*

- **Not a full contact-center.** One phone number per app instance.
- **Not E911-safe.** Do not route emergency calls through the
  persona — the provider's own TwiML/Telnyx settings handle 911.
- **Not a messaging backbone.** No group chats, no broadcasts, no
  mass templated sends. The tools are meant for 1-on-1 reminders
  and acks.
- **Not a voice clone on a phone.** The persona's TTS voice is the
  same one it uses in the app — Piper / Web Speech. No sonic
  "phone effect".

---

## 11. Further reading

- [docs/PHONE.md](./PHONE.md) — the live-call physics (turn-taking,
  barge-in, echo margin). Everything there applies to inbound PSTN
  too.
- MCP wizards live in **Projects → MCP Servers → Manage →
  Communication**. Each wizard deep-links to the real provider
  console (Twilio, Meta for Developers, BotFather).
- `backend/app/voice_call/ingress_bridge.py` — the ~150-LoC adapter
  that turns a provider webhook into a `voice_call` session.
- `agentic/integrations/mcp/{whatsapp,telegram,voip}/README.md` —
  per-connector docs.
