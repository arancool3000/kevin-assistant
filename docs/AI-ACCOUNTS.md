# Connect your Claude or ChatGPT account (optional)

Kevin talks with Google's Gemini, which is quick and great for everyday things. For **hard questions** — careful
maths, a bit of code, planning a trip, a long explanation — he can hand the question to **your own** Claude or
ChatGPT subscription and read you the answer.

- You need a **paid plan**: Claude Pro or Max, or ChatGPT Plus or Pro. It uses your plan's normal allowance.
- Kevin uses the companies' official command-line tools: **Claude Code** and **Codex**.
- They run with **no tools at all**. They can't read files on the Pi, run commands or browse, they only answer.
  Each question runs in an empty temporary folder with a two-minute limit.
- Nothing is sent to them unless you ask something hard. Kevin says "let me think about that" first.

You only need one of the two.

---

## 1. Install the tool on the Pi (once)

Connect to the Pi from your computer (`ssh <your user>@kevin.local`), then:

```sh
sudo apt install -y nodejs npm
sudo npm install -g @anthropic-ai/claude-code    # for Claude
sudo npm install -g @openai/codex                # for ChatGPT
```

The settings page shows **not connected** (rather than **not installed**) once it worked.

## 2a. Connect Claude

On **your own computer** (Windows, Mac or Linux), with Claude Code installed there too
(`npm install -g @anthropic-ai/claude-code`):

```sh
claude setup-token
```

A browser opens. Sign in to your Claude account and approve. The terminal then prints a long token starting
`sk-ant-`. Copy it, open Kevin's settings page (`http://kevin.local:8080`), paste it into **Claude** under
*Your Claude or ChatGPT account*, and press **Connect**.

The token is kept in `/etc/bob/secrets.json`, readable only by Kevin. **Disconnect** on the settings page forgets
it; you can also revoke it from your Claude account settings.

## 2b. Connect ChatGPT

On **your own computer**, with Codex installed (`npm install -g @openai/codex`):

```sh
codex login
```

Sign in with your ChatGPT account in the browser that opens. That writes a small sign-in file:

- Windows: `C:\Users\<you>\.codex\auth.json`
- Mac / Linux: `~/.codex/auth.json`

Open it in a text editor, copy **everything** in it, paste it into **ChatGPT** on Kevin's settings page and press
**Connect**. It's stored in Kevin's own folder on the Pi (`/var/lib/bob-assistant/codex`), readable only by him.

Treat that file like a password: don't share it or post it anywhere. **Disconnect** deletes it from the Pi; signing
out with `codex logout` on your computer ends that sign-in everywhere.

## 3. Try it

> "Hey Kevin, ask Claude to work out how long it takes to pay off a £2,000 loan at £150 a month with 9% interest."

> "Hey Kevin, think hard about this: plan a three-day trip to Edinburgh by train."

If both are connected, Kevin asks Claude unless you name ChatGPT.

## Troubleshooting

| Kevin says | Do this |
|---|---|
| "no Claude or ChatGPT account is connected yet" | Do step 2a or 2b; check the settings page says **connected**. |
| "...did not answer" | The token or sign-in has expired: connect again. Check your plan's usage limit. |
| "that took too long" | Ask a shorter question, or try again later. |
| Settings page says **not installed** | Do step 1 again and check `which claude` / `which codex` on the Pi. |
