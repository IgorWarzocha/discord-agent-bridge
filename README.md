# Discord → Grok Bot bridge

When someone in a Discord channel mentions this bot, the bridge emails **that person's** own Grok Bot. Nothing is hardwired to one account. A mention from Ada goes to Ada's address. Bob's mention goes to Bob's, and only if Bob has linked one.

A plain address wakes the bot itself. A plus-tagged address fires one routine. Those are equal modes:

| Mode | Address | What wakes |
| --- | --- | --- |
| `bot` | `name@mail.grokbot.com` | The Grok Bot, as a normal chat. No routine. |
| `routine` | `name+tag@mail.grokbot.com` | Only the routine listening on that tag. |

Mail is sent with Resend's HTTP API (`https://api.resend.com/emails`). There is no SMTP client, and there is no path from the bot back into Discord yet.

## Selection

A Discord user can save several links. Each link has an optional label.

The first word **after** the bot mention is the keyword:

- `@Grokbot research summarize the thread` selects the link labeled `research`.
- `@Grokbot please research this` does not. The first word is `please`, so the default link is used.
- `research @Grokbot hello` does not select `research` either. Words before the mention are ignored. The keyword is `hello`.
- The match is the whole first word, case-insensitive. `Research` matches `research`. `research,` does not.
- The keyword stays in the email. It only chooses the recipient.

The default is the link saved without a label. If every link has a label and none matches, the earliest link that user saved is used. The label `default` is reserved for that unlabeled link.

`/grok-status` shows the exact stored address (lowercased) so the plus-tag stays recognizable. That reply is ephemeral. The public channel reply after a mention does not repeat the address.

## Commands

| Command | What it does |
| --- | --- |
| `/link-grok email tag label` | Save a link for **you**. `email` is required. `tag` and `label` are optional. |
| `/unlink-grok label only_default` | `label` removes that link. `only_default` removes the unlabeled one. With neither, every link of yours is removed. |
| `/grok-status` and `/link-status` | List your links as `bot` or `routine`, the label, and the exact address. |

`email` must be on `mail.grokbot.com`. Anything else is rejected.

- `ada@mail.grokbot.com` is `bot`.
- `ada+research@mail.grokbot.com` is `routine`.
- `email: ada@mail.grokbot.com` plus `tag: research` is stored as `ada+research@mail.grokbot.com` (`routine`).
- A tag option on an address that already has a plus-tag is rejected, so the saved address cannot change by accident.

Addresses and labels are stored in lowercase. You can save 20 links. Linking the same label again replaces that address.

## What the email contains

Subject, on every mail:

```text
[Discord] #channel @username: first words
```

The body is plain text:

- Channel name, Discord username, user id, message link, timestamp.
- Mode (`bot` or `routine`), label (or `default`), and the exact `To` address.
- A callback webhook line. See [Future work](#future-work).
- The full tagged message, including the instruction after the mention.
- The parent message when the mention was a reply, or `not a reply`.
- A burst of the same author's recent messages, oldest first.
- Up to five earlier channel messages, under a separate heading, not mixed into the burst.

Burst rules:

- Look back **45 seconds** from the tagged message (this is inside the 30–60 second range; `BURST_WINDOW_SECONDS` may be set from 30 to 60).
- Walk backward through **that author's** messages only. Other people do not join the burst and do not split it.
- Stop at a gap longer than **5 seconds** between that author's consecutive messages (`BURST_GAP_SECONDS` may be set from 2 to 10).
- A gap of exactly 5 seconds is still inside the burst. The message 6 seconds earlier is not, even if it is inside the 45 second window.

The rate limit is **5 emails per 10 minutes per Discord user**, shared across that user's links. It is counted when a mention is accepted for sending, including when Resend later returns an error. It lives in memory and resets on restart. An author with no link does not consume a slot; the bot replies that they should use `/link-grok`.

## Grok Bot setup

Each person links an address on **their** Grok Bot. The bridge does not create bots or routines.

### bot — plain address

Use `/link-grok` with `name@mail.grokbot.com` and no tag.

Mail to that address wakes the Grok Bot itself: a normal chat-style wake. You do not create a routine for this mode. The bot should treat the email body as the task. The subject is `[Discord] #channel @user: first words`.

### routine — tagged address

Use either `name+tag@mail.grokbot.com`, or a plain address plus the `tag` option.

Mail to that address fires **only** the routine whose email trigger listens on that tag. It does not wake the bot's other routines, and it is not the plain chat wake.

The routine's wake carries headers only. The subject line is what that wake sees first. The routine reads the body itself and should treat the body as the task.

Routine email triggers default to `requireAuthPass`. SPF, DKIM, and DMARC must all pass. If they do not, the routine will not fire.

## Discord

1. Create an application and a bot at the Discord developer portal. Copy the bot token into `DISCORD_BOT_TOKEN`.
2. Turn on privileged **Message Content Intent**. Without it the bot cannot read the instruction after the mention.
3. The bot requests three intents only: **Guilds**, **Guild Messages**, and **Message Content**. It does not request members or presences.
4. Invite it with the `bot` and `applications.commands` scopes, and with permission to view the channel, send messages, and read message history.
5. For local development set `DISCORD_GUILD_ID` to that server's id so slash commands appear immediately. With it empty, commands are synced globally and Discord can take up to an hour to show them.

This repository does not connect to Discord on its own. `python main.py` is what logs in.

## Resend

Create an API key and set `RESEND_API_KEY`.

Set `RESEND_FROM` to an address on a domain you have verified in Resend, for example `Grokbot Bridge <bridge@your-verified-domain.com>`.

Verify that domain and enable SPF and DKIM. The domain in `RESEND_FROM` has to **align** with those records. Routine triggers default to `requireAuthPass`, so SPF, DKIM, and DMARC must pass. If the sending domain is not aligned, the message may be accepted by Resend and still **not fire the routine**.

`bot` mode is still ordinary email from that same From address. Use a verified, aligned domain for both modes.

## Run locally

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# fill DISCORD_BOT_TOKEN, RESEND_API_KEY, and RESEND_FROM
python main.py
```

Links are stored in SQLite at `DATABASE_PATH` (default `data/links.sqlite3`) and survive restarts. `.env` is gitignored. Do not commit tokens.

| Variable | Required | Default | Role |
| --- | --- | --- | --- |
| `DISCORD_BOT_TOKEN` | yes | | Bot token |
| `DISCORD_GUILD_ID` | no | global sync | Server id for fast slash-command sync |
| `RESEND_API_KEY` | yes | | Resend HTTP API key |
| `RESEND_FROM` | yes | | Verified, SPF/DKIM-aligned sender |
| `DATABASE_PATH` | no | `data/links.sqlite3` | SQLite file |
| `RATE_LIMIT_MAX` | no | `5` | Sends per user per window |
| `RATE_LIMIT_WINDOW_SECONDS` | no | `600` | Rate-limit window |
| `BURST_WINDOW_SECONDS` | no | `45` | Lookback, 30–60 |
| `BURST_GAP_SECONDS` | no | `5` | Same-author gap, 2–10 |
| `CHANNEL_TAIL_COUNT` | no | `5` | Earlier channel messages, 0–10 |
| `CALLBACK_WEBHOOK_URL` | no | empty | Copied into the body only |

## Tests

Unit tests mock Discord and Resend. They open no sockets and do not send mail.

```bash
python -m pytest
```

Burst building, plus-tag validation, link selection, and the subject/body are covered without a live server.

## Future work

The email body has a **callback webhook** line. If `CALLBACK_WEBHOOK_URL` is set, that URL is written into the body and nothing else happens. The bridge does not receive mail, does not listen for a webhook, and does not post a reply back to Discord. A later version could accept a call from the routine and send it to the channel.

## Layout

| Module | Owns |
| --- | --- |
| `grokbot_bridge/address.py` | `mail.grokbot.com` validation, `bot` vs `routine` |
| `grokbot_bridge/registry.py` | SQLite links, labels, the 20-link cap |
| `grokbot_bridge/mentions.py` | The keyword after the mention |
| `grokbot_bridge/burst.py` | Burst and earlier-channel tail |
| `grokbot_bridge/payload.py` | Subject and plain-text body |
| `grokbot_bridge/routing.py` | Which of the author's links is used |
| `grokbot_bridge/commands.py` | `/link-grok`, `/unlink-grok`, status text |
| `grokbot_bridge/resend.py` | Resend HTTP send |
| `grokbot_bridge/discord_app.py` | The only Discord client |
| `grokbot_bridge/settings.py` | Environment |
| `main.py` | Process entry. This is what connects to Discord. |
