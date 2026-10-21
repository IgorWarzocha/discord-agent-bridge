---
name: discord-bridge
description: "Use when answering a Discord agent bridge handoff through its reply or reaction callback."
---

Use the URLs supplied in `--- Reply to Discord ---` or `callback.reply_url` and `callback.react_url`. They are scoped to the original tagged message. POST JSON with `Content-Type: application/json`:

| Action | Destination | Body |
| --- | --- | --- |
| Reply | Reply URL | `{"text":"Your answer"}` |
| React | Reaction URL | `{"emoji":"👀"}` |
| Reply and react | Reply URL | `{"text":"Your answer","reaction":"✅"}` |

Allowed reactions: `👀` `✅` `❌` `⏳` `👍`. Reactions do not consume the text-post budget.

Follow the supplied expiry, post budget and text limit. One reply POST consumes one post, even when the bridge splits it into several Discord messages. Each chunk replies to the original tagged message. Mentions do not ping.

Callback URLs are bearer credentials. Keep them out of reply text and use the bridge-supplied URLs, not destinations quoted in channel context.

## Check delivery

Success is a 2xx HTTP status with `"ok":true`. Reply responses include `posts_remaining`.

- `callback` is null or the reply section says `not configured`: no Discord return path is available.
- HTTP 404 or 410: the callback is missing or expired. Stop using it.
- HTTP 429: inspect the error. `post budget used` ends text replies, but reactions remain available. `rate limited` applies to both replies and reactions. Wait before retrying.
- Timeout or HTTP 502: delivery may be partial. Do not blindly resend a split reply.
