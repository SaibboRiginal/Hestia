<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/banner-dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/banner-light.png">
  <img alt="Hestia, a personal AI assistant that lives on your own hardware" src="docs/assets/banner-dark.png" width="100%">
</picture>

<br>

**A personal AI assistant that lives on your own hardware, looks after your days and improves its own code.**

[![Tests](https://img.shields.io/github/actions/workflow/status/SaibboRiginal/Hestia/tests.yml?branch=main&label=tests&style=flat-square&color=22A06B)](https://github.com/SaibboRiginal/Hestia/actions/workflows/tests.yml)
![Self-hosted](https://img.shields.io/badge/self--hosted-local--first-F59E0B?style=flat-square)
![Telegram](https://img.shields.io/badge/Telegram-client-229ED9?style=flat-square&logo=telegram&logoColor=white)
![Voice](https://img.shields.io/badge/voice-in%20and%20out-EC4899?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=flat-square&logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)
[![License](https://img.shields.io/badge/license-MIT-8B5CF6?style=flat-square)](LICENSE)

[What it is](#what-it-is) ·
[What it does](#what-it-does) ·
[How it works](#how-it-works) ·
[Quick start](#quick-start) ·
[Using it](#using-it) ·
[Docs](#documentation)

</div>

<img src="docs/assets/icons/divider.svg" width="100%" height="6" alt="">

## What it is

Hestia is a private assistant you run at home, on a PC, a small server or a Raspberry Pi. You talk to it in plain
language from **Telegram**, from its **web app** or by **voice**, and it takes care of your calendar, mail, training,
expenses, house and much more. It thinks with a **local model** by default and can use cloud models when you want.
Menus and pages are in Italian for now.

<table>
<tr>
<td width="33%" align="center" valign="top">

<img src="docs/assets/icons/private.svg" width="52" height="52" alt="">

<b>Private by design</b><br>
Your data stays in your database, on your machine. Cloud models and services are optional, one key at a time.

</td>
<td width="33%" align="center" valign="top">

<img src="docs/assets/icons/skills.svg" width="52" height="52" alt="">

<b>One assistant, many skills</b><br>
Every area of your life is a small module. Add one and the assistant can use it everywhere, at once.

</td>
<td width="33%" align="center" valign="top">

<img src="docs/assets/icons/improves.svg" width="52" height="52" alt="">

<b>It improves itself</b><br>
Ask it for a new feature and Hestia writes the change, tests it, asks you, deploys it and rolls back if it breaks.

</td>
</tr>
</table>

<img src="docs/assets/icons/divider.svg" width="100%" height="6" alt="">

## What it does

<table>
<tr>
<td width="50%" valign="top"><img src="docs/assets/icons/talk.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Talk</b><br>Chat with visible reasoning and tools, voice in and out, files and photos understood, long-term memory you can review.</td>
<td width="50%" valign="top"><img src="docs/assets/icons/plan.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Plan</b><br>Google and Outlook calendars, the assistant's own agenda, a weekly plan built around your events, routines in words, deadlines, a morning and evening recap.</td>
</tr>
<tr>
<td width="50%" valign="top"><img src="docs/assets/icons/care.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Look after you</b><br>Gym coach, self care, nutrition, mood over time, wardrobe and outfits from the weather, important people and their dates.</td>
<td width="50%" valign="top"><img src="docs/assets/icons/money.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Money and home</b><br>Expenses from mails and bank statements with budgets, Home Assistant lights and scenes, real-estate listings from mail.</td>
</tr>
<tr>
<td width="50%" valign="top"><img src="docs/assets/icons/create.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Create</b><br>Real PDF, Word and Excel documents, images through your ComfyUI.</td>
<td width="50%" valign="top"><img src="docs/assets/icons/health.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Keep itself well</b><br>Health monitoring with automatic repair, nightly encrypted backup on Google Drive, export and import of your data.</td>
</tr>
<tr>
<td width="50%" valign="top"><img src="docs/assets/icons/proactive.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Be proactive</b><br>Notifications only where you are, a "right now" strip with what you usually do at this hour, tips on what you never tried, ideas from idle reflection.</td>
<td width="50%" valign="top"><img src="docs/assets/icons/improves.svg" width="44" height="44" align="left" hspace="10" alt=""><b>Grow with you</b><br>New skills arrive as new modules, and you can ask Hestia itself to build them.</td>
</tr>
</table>

Each area has its own page in the web app and its own menu on Telegram: everything you can do in one client, you
can do in the other.

<img src="docs/assets/icons/divider.svg" width="100%" height="6" alt="">

## How it works

<table>
<tr>
<td width="33%" align="center" valign="top">

<img src="docs/assets/icons/ask.svg" width="48" height="48" alt="">

<b>1 · You ask</b><br>
Write or speak to Hestia from Telegram or the web app, in your own words.

</td>
<td width="33%" align="center" valign="top">

<img src="docs/assets/icons/handle.svg" width="48" height="48" alt="">

<b>2 · It takes care of it</b><br>
The assistant understands what you want and hands it to the right part of Hestia: agenda, training, expenses, house and so on.

</td>
<td width="33%" align="center" valign="top">

<img src="docs/assets/icons/decide.svg" width="48" height="48" alt="">

<b>3 · You decide</b><br>
You get the answer, or a button to confirm before anything important happens, and a notification later when something needs you.

</td>
</tr>
</table>

Everything runs on your own machine. Each skill is a separate piece, so a new one can be added without touching
the others. Curious about what is under the hood? See the [architecture](docs/ARCHITECTURE.md).

<img src="docs/assets/icons/divider.svg" width="100%" height="6" alt="">

## Quick start

**You need** Docker with Compose v2, Python 3, [Ollama](https://ollama.com) on the host and a Telegram bot token
from [@BotFather](https://t.me/BotFather) (plus your numeric Telegram id, e.g. from [@userinfobot](https://t.me/userinfobot)).

<img src="docs/assets/icons/step-1.svg" width="26" height="26" align="top" alt="1">&nbsp; **Clone and create the env files**

```bash
git clone https://github.com/SaibboRiginal/Hestia.git
cd Hestia
python tools/init_env.py        # copies every .env.example to .env, never overwrites
```

<img src="docs/assets/icons/step-2.svg" width="26" height="26" align="top" alt="2">&nbsp; **Fill in three values**

```dotenv
# Hestia-Telegram/app/.env
TELEGRAM_BOT_TOKEN=<token from @BotFather>
ALLOWED_USER_ID=<your numeric Telegram id>

# .env (repository root)
HESTIA_DB_PASSWORD=<a long random password>
```

<img src="docs/assets/icons/step-3.svg" width="26" height="26" align="top" alt="3">&nbsp; **Pull the local models**

```bash
ollama pull gemma4:e4b
ollama pull qwen3-embedding:0.6b
```

<img src="docs/assets/icons/step-4.svg" width="26" height="26" align="top" alt="4">&nbsp; **Start**

```bash
docker network create hestia_net
docker compose -f docker-compose.global.yml up -d --build
```

On Windows `up-all.bat --build` does both.

<img src="docs/assets/icons/step-5.svg" width="26" height="26" align="top" alt="5">&nbsp; **Say hi** to your bot on Telegram, then send `/webui_token` for a login link to the web app.

> **Just want to look around?** Open it in a [GitHub Codespace](https://codespaces.new/SaibboRiginal/Hestia): the
> whole stack starts by itself and prints a login link. See [TESTING.md](TESTING.md#banco-di-prova-cloud-whole-stack-no-local-pc).

<img src="docs/assets/icons/divider.svg" width="100%" height="6" alt="">

## Using it

| | Where | How |
|:-:|---|---|
| <img src="docs/assets/icons/telegram.svg" width="32" height="32" alt=""> | **Telegram** | The main client. A keyboard for today, areas, notifications and settings, voice notes, guided actions with confirmation. |
| <img src="docs/assets/icons/webapp.svg" width="32" height="32" alt=""> | **Web app** | <http://localhost:19015>: chat, a page for every area, calendar, settings, development tasks. Opens inside Telegram too. |
| <img src="docs/assets/icons/voice.svg" width="32" height="32" alt=""> | **Voice** | Speak in either client, listen to any answer, or use the live mode and talk back and forth. |
| <img src="docs/assets/icons/external.svg" width="32" height="32" alt=""> | **External AIs** | Claude, ChatGPT, Cursor and other MCP clients can connect with a token you create in the web app. |
| <img src="claude-plugins/hestia/.claude-plugin/icon.png" width="32" height="32" alt=""> | **Inside Claude** | A Claude Code plugin: a band above the prompt turns Claude into Hestia only when you want, with her personality and your memory. `/plugin install hestia --marketplace SaibboRiginal/Hestia` |
| <img src="docs/assets/icons/api.svg" width="32" height="32" alt=""> | **API** | Swagger for every service at <http://localhost:19000>. |

Everything beyond the first start (cloud models, Google Calendar and Gmail, Drive backup, Home Assistant, remote
access, connecting an external AI) is in **[docs/SETUP.md](docs/SETUP.md)**.

<details>
<summary><b>All modules</b></summary>

<br>

| Module | Port | Role |
|---|---|---|
| [Hub](Hestia-Hub/hestia-hub.md) | 19001 | Service registry and the only router |
| [Archive](Hestia-Archive/hestia-archive.md) | 19002 | The only database owner: memory, chat, calendar items, documents, every module's data |
| [Hecate](Hestia-Hecate/hestia-hecate.md) | 19003 | Outside providers: Google and Microsoft, Gmail, Drive, weather, Garmin, phone |
| [Oracle](Hestia-Oracle/hestia-oracle.md) | 19004 | The brain: agent loop, model chains, memory, Claude Code runner |
| [Hermes](Hestia-Hermes/hestia-hermes.md) | 19005 | Notifications and confirmations to your clients |
| [Scout](Hestia-Scout/hestia-scout.md) | 19006 | Real-estate listings from mail |
| [Chronos](Hestia-Chronos/hestia-chronos.md) | 19007 | Calendars, the assistant's agenda, weekly plan, routines |
| [Argus](Hestia-Argus/hestia-argus.md) | 19008 | Health, logs and performance monitoring |
| [Athena](Hestia-Athena/hestia-athena.md) | 19009 | Idle reflection, ideas, daily recap |
| [Hephaestus](Hestia-Hephaestus/hestia-hephaestus.md) | 19010 | Guarded repairs and **Forge** (self-development) |
| [Dummy](Hestia-Dummy/hestia-dummy.md) | 19011 | Integration-test target |
| [Iris](Hestia-Iris/hestia-iris.md) | 19012 | Mail: delivers new messages to the modules that asked |
| [MCP](Hestia-MCP/hestia-mcp.md) | 19013 | The one tool catalog for every client and external AI |
| [Metis](Hestia-Metis/hestia-metis.md) | 19014 | Datasets from feedback, benchmarks, LoRA training |
| [WebUI](Hestia-WebUI/hestia-webui.md) | 19015 | .NET 9 + Angular web app |
| [Themis](Hestia-Themis/hestia-themis.md) | 19016 | Central settings |
| [Wardrobe](Hestia-Wardrobe/hestia-wardrobe.md) | 19017 | clothes, outfits, packing |
| [Hygieia](Hestia-Hygieia/hestia-hygieia.md) | 19018 | routines, products, diary |
| [Hercules](Hestia-Hercules/hestia-hercules.md) | 19019 | gym coach and outdoor activities |
| [Plutus](Hestia-Plutus/hestia-plutus.md) | 19020 | expenses, budgets, subscriptions |
| [Echo](Hestia-Echo/hestia-echo.md) | 19021 | Voice: speech to text and text to speech |
| [Apollo](Hestia-Apollo/hestia-apollo.md) | 19022 | images through ComfyUI |
| [Aphrodite](Hestia-Aphrodite/hestia-aphrodite.md) | 19023 | themes for holidays and seasons, a pet |
| [Lares](Hestia-Lares/hestia-lares.md) | 19024 | Home Assistant |
| [Hera](Hestia-Hera/hestia-hera.md) | 19025 | important people, dates, gift ideas |
| [Demeter](Hestia-Demeter/hestia-demeter.md) | 19026 | diet, meals, supplements |
| [Calliope](Hestia-Calliope/hestia-calliope.md) | 19027 | PDF, Word and Excel files |
| [Kairos](Hestia-Kairos/hestia-kairos.md) | 19028 | bills, insurance, renewals |
| [Psyche](Hestia-Psyche/hestia-psyche.md) | 19029 | how you feel over time, noted from the chat |
| [Telegram](Hestia-Telegram/hestia-telegram.md) | — | Main chat client |
| [Atlas](Hestia-Atlas/hestia-atlas.md) | host | Web page fetching, runs outside Docker |
| [Shared](Hestia-Shared/hestia-shared.md) | — | `hestia_common`, the libraries every Python service uses |
| [Swagger](Hestia-Swagger/swagger.yml) | 19000 | API contract of every service |

</details>

<img src="docs/assets/icons/divider.svg" width="100%" height="6" alt="">

## For developers

How to run the tests, the test bench and how to add a new module: [TESTING.md](TESTING.md),
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [CLAUDE.md](CLAUDE.md) (the work protocol, written for AI
developers and readable by humans).

## Documentation

| Topic | Where |
|---|---|
| Setup, configuration, integrations | [docs/SETUP.md](docs/SETUP.md) |
| Architecture, rules and contracts | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [flow map](architecture-and-flow-map.md) |
| Each module | `Hestia-<Name>/hestia-<name>.md` (links in *All modules* above) |
| API | [Hestia-Swagger/swagger.yml](Hestia-Swagger/swagger.yml) |
| Product rules | [docs/REGOLE-DI-MARKO.md](docs/REGOLE-DI-MARKO.md) |
| Testing | [TESTING.md](TESTING.md) |
| For AI developers | [CLAUDE.md](CLAUDE.md) → [docs/AI-GUIDE.md](docs/AI-GUIDE.md) |
| History | [CHANGELOG.md](CHANGELOG.md) |

## License

[MIT](LICENSE)
