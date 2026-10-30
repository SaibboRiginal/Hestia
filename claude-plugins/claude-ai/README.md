# Hestia skill for claude.ai (web, desktop chat, phone)

claude.ai chats have no band above the prompt, so there Hestia is switched on by asking. Two steps, once:

1. Add Hestia as a **custom connector** (Settings → Connectors) with `https://<your-hostname>/mcp`; allow it on
   Hestia's *Accessi AI* page.
2. Zip the `hestia/` folder next to this file (`cd claude-plugins/claude-ai && zip -r hestia.zip hestia`) and upload
   it in Settings → Capabilities → Skills.

Then «parla come Hestia» or «Hestia, …» loads her persona, your instructions and memory from your Hestia.
