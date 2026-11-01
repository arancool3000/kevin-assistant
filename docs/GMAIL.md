# Gmail (read-only, optional)

Kevin can tell you how many unread emails you have and who the newest are from ("Any new emails?", "Anything from
school?"). It is **off** until you connect it, and it uses **your own** Google OAuth client: this project ships no
Google credentials and never will. The only permission is `gmail.readonly`: Kevin cannot send, delete or change mail.

## 1. Make your own OAuth client (once, about 5 minutes)

1. Go to <https://console.cloud.google.com/>, create a project (any name).
2. **APIs & Services > Library**: enable the **Gmail API**.
3. **APIs & Services > OAuth consent screen**: User type *External*, fill in an app name and your email, add the
   scope `.../auth/gmail.readonly`, and add your own Google address under **Test users**.
4. **APIs & Services > Credentials > Create credentials > OAuth client ID**, type **Desktop app**. Download the
   JSON file (`client_secret_....json`).

While the app is in *Testing*, Google expires the sign-in after 7 days: either repeat step 2 when it stops working,
or press **Publish app** on the consent screen (for your own use Google shows an "unverified app" warning when you
sign in; that is expected for a client you made yourself).

## 2. Connect Kevin

Copy the JSON file to the Pi, then:

```
sudo install -m 600 -o bob-assistant client_secret_*.json /tmp/gmail-client.json
sudo -u bob-assistant BOB_ETC=/etc/bob /opt/bob-assistant/venv/bin/python -m bob.gmail setup /tmp/gmail-client.json
sudo rm /tmp/gmail-client.json
sudo systemctl restart bob-assistant
```

It prints a link: open it on any device, sign in and allow read-only access. The browser then goes to a
`http://localhost/?code=...` address that does not load: copy that whole address and paste it into the Pi.

The client id/secret and the refresh token are saved in `/etc/bob/secrets.json` (readable only by Kevin) and
`gmail_enabled` is switched on.

## Disconnect

```
sudo -u bob-assistant /opt/bob-assistant/venv/bin/python -m bob.gmail forget
```

and remove the app at <https://myaccount.google.com/permissions>.
