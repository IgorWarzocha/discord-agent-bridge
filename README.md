# Discord agent bridge

A Discord mention is delivered to the agent **that user** connected. Grok Bot is one connector. Webhook, Hermes, and OpenClaw are others. Nothing is hardwired to one account.

The core does not know how an agent is woken. It builds one payload and calls `connector.deliver`.

After `/connect`, type `@bot your request` to use your default connection, or `@bot label your request` to select a labelled link. Literal `@bot` text works without choosing an autocomplete mention. A native Discord mention of the bridge works too.

## Architecture

```
Discord mention
  -> burst + earlier channel + reply parent
  -> BridgePayload
  -> the link's connector
```

| Piece | Owns |
| --- | --- |
| `discord_agent_bridge/discord_app.py` | The only Discord client. Slash commands and the mention listener. |
| `discord_agent_bridge/burst.py` | Same-author burst and the earlier-channel tail. |
| `discord_agent_bridge/payload.py` | `BridgePayload`, the subject line, the plain-text task, and the JSON object. |
| `discord_agent_bridge/registry.py` | SQLite links: Discord user, label, connector type, validated config. |
| `discord_agent_bridge/routing.py` | Label selection, rate limit, callback token, `deliver`. |
| `discord_agent_bridge/callbacks.py` | Hashed reply tokens and hop tracking. |
| `discord_agent_bridge/replies.py` | `POST /reply/<token>` and `POST /react/<token>`. |
| `discord_agent_bridge/hops.py` | The bridge never retriggers itself. Other bots need an allowlist. |
| `discord_agent_bridge/connectors/` | One module per agent, registered in `catalog.py`. |

A link is `type` + optional `label` + config that the type's `validate` method accepted. The first word after the bot mention selects a label. Anything else uses the unlabeled default. If every link has a label and none matches, the earliest link is used.

`/status` shows the connector's `describe` text. Secrets (webhook HMAC, Hermes secret, OpenClaw token) are not included.

## Commands

| Command | What it does |
| --- | --- |
| `/connect type label ...` | Save a link for you. `type` is one of the registered connectors. |
| `/disconnect` | Remove one label, only the default, or every link you saved. |
| `/status` | List your links. |

`/connect` lists the connectors enabled on this deployment. Its options are `email` and `tag` (grokbot), `url` (webhook, Hermes, OpenClaw), `secret` (webhook, Hermes), `token` and `agent_id` (OpenClaw). Each connector ignores options it does not use and rejects a config that is missing what it requires.

## Reply path

When `CALLBACK_BASE_URL` is set and the connector's `supports_callback` is true, the payload includes a callback. Every connector in this repo sets that flag, because each one hands the agent text it can act on.

`POST /reply/<token>` with `{"text":"..."}` replies to the original tagged message as `↩ reply from <user>'s Grok Bot`, split at 2000 characters, with mentions disabled. The link allows **5 posts** and lasts **24 hours**. `CALLBACK_TTL_HOURS=0` does not expire. `POST /react/<token>` with `{"emoji":"👀"}` adds `👀` `✅` `❌` `⏳` or `👍` and does not use a post. Both share the per-channel callback rate limit.

The bridge reacts `📨` when delivery succeeds and `⚠️` when it fails.

Install `skills/discord-bridge/SKILL.md` as a skill named `discord-bridge` on the receiving agent. It covers replies, reactions, callback limits and delivery failures across all connectors. The bridge does not install it. For a Grok Bot routine, install it on the routine receiving the plus-tagged email.

The bridge's own messages never start another delivery. Other bots and webhooks are ignored unless their user id is in `BOT_ALLOWLIST`. After `MAX_HOPS` bot-to-bot mentions (default 3) the thread stops.

## Burst

From the tagged message, walk backward through that author's messages. Keep a message when it is inside 45 seconds and the gap to the next newer message from that author is at most 5 seconds. Other people do not join or split the burst. Then add up to 5 earlier channel messages, excluding the burst and the reply parent, under a separate heading.

## Write a connector

1. Add `discord_agent_bridge/connectors/<name>.py`.
2. Set `type` to a new member of `ConnectorType` in `connectors/protocol.py`.
3. Implement `validate`, `describe`, and `deliver`. `describe` must not return secrets. `deliver` receives a `BridgePayload` and returns `DeliveryResult`.
4. Set `capabilities = Capabilities(supports_callback=True)` if the agent can read the callback instructions and POST back. Otherwise set it false and the core omits the callback.
5. Register the instance in `build_connectors` in `connectors/catalog.py`.

`validate` is the schema. It receives the slash-command options that the user filled in (`email`, `tag`, `url`, `secret`, `token`, `agent_id`) and returns the dict stored in SQLite. Reject anything that is not a real configuration for that agent.

Do not send from tests. Pass a fake `HttpTransport` or `ResendSender` transport.

## Connectors

### grokbot

Resend HTTP API (`https://api.resend.com/emails`). No SMTP.

| Address | Mode | What wakes |
| --- | --- | --- |
| `name@mail.grokbot.com` | `bot` | The Grok Bot itself, as a normal chat. No routine. |
| `name+tag@mail.grokbot.com` | `routine` | Only the routine listening on that tag. |

`/connect type:grokbot email:... tag:...`. A tag option builds `name+tag@` from a plain address. Other domains are rejected.

The routine's wake carries headers only, so it must read the body. The subject is `[Discord] #channel @user: first words`. The callback curl is in the body.

Routine triggers default to `requireAuthPass`. The Resend domain in `RESEND_FROM` must be verified with SPF and DKIM aligned, and DMARC must pass, or the routine will not fire.

### webhook

Generic signed HTTPS POST of the normalised JSON (`BridgePayload` via `to_json`).

```
POST <url>
X-Webhook-Timestamp: <unix seconds>
X-Webhook-Signature: sha256=<hex HMAC-SHA256 of "{timestamp}.{raw body}">
```

The secret is at least 16 characters and is not shown by `/status`. This is the bridge's own signature, for anything that can verify an HMAC. It is not a vendor API.

### hermes

Nous Research Hermes Agent accepts inbound POSTs on a webhook route.

- Guide: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks
- Signature check in the gateway: https://github.com/NousResearch/hermes-agent/blob/72ff3e90/gateway/platforms/webhook.py

Point `url` at the route, for example `https://hermes.example/webhooks/discord`. `secret` is that route's HMAC secret (or the gateway `WEBHOOK_SECRET` fallback). The default port in the Hermes docs is `8644`, path `/webhooks/<route>`.

The bridge sends the normalised JSON as the body. With no `prompt` template, Hermes dumps that JSON into the agent prompt. Two signatures are sent, matching the docs:

- `X-Webhook-Signature`: HMAC-SHA256 hex of the raw body (V1, what the gateway source above checks).
- `X-Webhook-Signature-V2` plus `X-Webhook-Timestamp`: HMAC-SHA256 hex of `{timestamp}.{body}` (V2, recommended in the guide, timestamp within ±300 seconds).

### openclaw

OpenClaw's gateway accepts authenticated hook POSTs.

- https://docs.openclaw.ai/gateway/config-hooks
- https://docs.openclaw.ai/automation/cron-jobs/webhooks

`url` is the gateway origin (`https://gateway.example.com`) or the full `.../hooks/agent` URL. `token` is the hook token (`Authorization: Bearer`). Optional `agent_id` is sent as `agentId`.

The bridge POSTs `{"message": "<task text>", "name": "Discord", "deliver": false}`. `message` is required by the docs. `deliver: false` skips OpenClaw announcing to some other channel; the callback URL is inside the message so the agent posts back here. The token is not written into the body and is not shown by `/status`.

## Discord

1. Create an application and a bot. Put the token in `DISCORD_BOT_TOKEN`.
2. Turn on privileged **Message Content Intent**.
3. The process requests **Guilds**, **Guild Messages**, and **Message Content** only.
4. Invite it with scopes `bot` and `applications.commands`, and permission to view the channel, send messages, read message history, and add reactions.
5. Set `DISCORD_GUILD_ID` while developing so slash commands appear immediately. Without it, global sync can take up to an hour.

`python main.py` is what logs in. Tests do not.

## Resend

Set both `RESEND_API_KEY` and `RESEND_FROM` to enable grokbot, or leave both empty to run only the HTTP connectors. The From address must use a verified domain. SPF and DKIM must align with that domain. Routine email triggers default to `requireAuthPass` (SPF, DKIM, and DMARC). If they do not pass, a grokbot routine will not fire.

## Hosting

Run this on the always-on server. Agents that answer through the callback must reach `POST /reply/<token>` and `POST /react/<token>`, so `CALLBACK_BASE_URL` has to be public HTTPS. The process binds `127.0.0.1:8787` by default and does not open a public port. Nothing here starts a tunnel.

Choose one:

- **Cloudflare Tunnel** (`cloudflared`) from `127.0.0.1:8787` to a hostname you control. Set `CALLBACK_BASE_URL` to that `https://` origin.
- **Caddy or nginx** on the server, with a real certificate, proxying to `127.0.0.1:8787`. Keep the app port off the public firewall.
- **Tailscale Funnel** only if the agent that answers can open that URL. A tailnet the agent is outside of will not work.

## Run locally

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Links live in SQLite at `DATABASE_PATH` (default `data/links.sqlite3`). `.env` is gitignored.

| Variable | Required | Default | Role |
| --- | --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | | Bot token |
| `DISCORD_GUILD_ID` | no | global sync | Server id for fast slash-command sync |
| `RESEND_API_KEY` | for grokbot | | Used by the grokbot connector |
| `RESEND_FROM` | for grokbot | | Verified, SPF/DKIM-aligned sender |
| `DATABASE_PATH` | no | `data/links.sqlite3` | SQLite file |
| `RATE_LIMIT_MAX` | no | `5` | Deliveries per Discord user per window |
| `RATE_LIMIT_WINDOW_SECONDS` | no | `600` | That window |
| `BURST_WINDOW_SECONDS` | no | `45` | Lookback, 30–60 |
| `BURST_GAP_SECONDS` | no | `5` | Same-author gap, 2–10 |
| `CHANNEL_TAIL_COUNT` | no | `5` | Earlier channel messages |
| `CALLBACK_BASE_URL` | no | empty | Public https base. Empty means no callback is issued |
| `CALLBACK_TTL_HOURS` | no | `24` | `0` means the link does not expire |
| `CALLBACK_MAX_POSTS` | no | `5` | Text posts per link |
| `CALLBACK_TEXT_LIMIT` | no | `8000` | Maximum reply `text` |
| `CALLBACK_RATE_LIMIT_MAX` | no | `20` | Callback posts and reactions per channel |
| `CALLBACK_RATE_LIMIT_WINDOW_SECONDS` | no | `600` | Callback rate-limit window |
| `MAX_HOPS` | no | `3` | Bot-to-bot mentions forwarded in one thread |
| `BOT_ALLOWLIST` | no | empty | Discord user ids allowed to mention this bot |
| `HTTP_HOST` | no | `127.0.0.1` | Callback bind address |
| `HTTP_PORT` | no | `8787` | Callback bind port |

## Tests

```bash
python -m pytest
```

The suite is small and does not connect to Discord, Resend, Hermes, or OpenClaw. HTTP connectors use a fake transport. The tests block socket connect and bind.

## Security

- Callback tokens are random, stored as SHA-256, and compared with `hmac.compare_digest`.
- Logs record the callback route, status, user id, and channel id. They do not record the token, the reply text, or connector secrets.
- Discord replies use `allowed_mentions` with an empty parse list, and `mention_author` is off.
- Webhook and Hermes signatures use HMAC-SHA256. The OpenClaw token is sent only as a Bearer header.
