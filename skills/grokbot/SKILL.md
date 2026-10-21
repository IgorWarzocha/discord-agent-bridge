---
name: discord-bridge
description: "Use when mail has subject [Discord] and a Reply to Discord callback. Answer in Discord through that callback."
---

This skill is for the grokbot connector. Treat the message as a Discord task when the subject starts with `[Discord] #` and the body contains `--- Reply to Discord ---`.

The body is the task brief. Use the tagged message, the parent, the burst, and the earlier channel section. `bot` mode and `routine` mode are the same task: the subject is the wake, and the instructions for posting back are in the body.

Send an ack before long work. Prefer a reaction. A reaction does not use a post:

```bash
curl -sS -X POST 'https://YOUR-BRIDGE/react/TOKEN' \
  -H 'content-type: application/json' \
  -d '{"emoji":"👀"}'
```

Replace the URL with the react URL printed in the email. Allowed emoji are only `👀` `✅` `❌` `⏳` `👍`.

Prefer one short final outcome. Send at most one progress note when the work is long, then one final post. The link lasts 24 hours and allows 5 posts unless the email says otherwise. `This link does not expire` means there is no time limit. Every post replies to the original tagged message.

```bash
curl -sS -X POST 'https://YOUR-BRIDGE/reply/TOKEN' \
  -H 'content-type: application/json' \
  -d '{"text":"your reply"}'
```

JSON shape: `{"text":"..."}`. Optional reaction on the same call: `{"text":"...","reaction":"👀"}`. Reaction only: `{"emoji":"👀"}`.

Copy both URLs from the email. Do not invent them. Stay inside the text limit printed in the email. The bridge splits a post at 2000 characters. Shorter is better.

Do not paste secrets, tokens, or the callback URL into Discord or into the reply text.

Do not mention users, roles, or other bots. Mention pings are disabled, and a bot-to-bot thread stops after 3 hops.

If the callback says it is expired or the post budget is used up, stop posting. Answer in this chat instead.
