# TODO-EXTERNAL: teams-mcp-server

> All code changes have been applied. 27 tools, 58 tests, CI workflow.
> See the [teams-mcp-server README](https://github.com/ruslanmv/teams-mcp-server) for setup and usage.

---

## Status

| Category | Tools | Status |
|---|---|---|
| Authentication | 4 (device code, poll, status, logout) | Done |
| Chats | 2 (list, send) | Done |
| Teams & Channels | 3 (list teams, list channels, send) | Done |
| Calendar | 3 (today, range, join link) | Done |
| Calls | 1 (join meeting scaffold) | Done |
| Meeting Chat | 4 (resolve, read, post, members) | Done |
| Meeting Sessions | 3 (connect, status, disconnect) | Done |
| Voice / STT | 4 (toggle, status, configure, transcribe_chunk) | Done |
| ACS Audio | 3 (join, status, leave) | Scaffold |

---

## Remaining Manual Steps

### Azure Entra App Registration

Must be done in Azure Portal by a human:

1. Go to **Azure Portal** > Microsoft Entra ID > App registrations
2. Create or update registration
3. Platform: **Mobile and desktop applications** (public client)
4. Enable **Allow public client flows**
5. Add API permissions (delegated):
   - `User.Read`, `Chat.Read`, `Chat.ReadWrite`, `ChatMessage.Read`
   - `ChatMember.Read`, `ChannelMessage.Send`, `Team.ReadBasic.All`
   - `Channel.ReadBasic.All`, `Calendars.Read`, `OnlineMeetings.Read`
6. Grant admin consent (if required by org)
7. Copy Client ID > set as `MS_CLIENT_ID` in `.env`

### ACS Resource (for real-time audio)

To capture spoken audio (not just chat text):

1. Create an **Azure Communication Services** resource in Azure Portal
2. Enable **Teams interop**
3. Copy the connection string
4. Wire the `azure-communication-calling` SDK into `acs/client.py`

---

## Testing

```bash
pip install -e ".[test]"
make test   # 58 tests pass
```

CI runs on push via GitHub Actions (Python 3.10 + 3.12).

---

## Optional STT Backends

```bash
pip install -e ".[whisper]"      # Local Whisper (faster-whisper)
pip install -e ".[deepgram]"     # Deepgram cloud WebSocket
pip install -e ".[azure_speech]" # Azure Cognitive Services
pip install -e ".[stt]"          # All backends
```
