---
title: Authentication
description: Sign in on your own device and recover an expired LEARN session.
---

You sign in yourself. Agent2Learn opens a **dedicated Chrome or Edge profile**, separate from your everyday browser, and uses the resulting LEARN session on that same computer.

```bash
a2l auth
```

Finish WatIAM and Duo in that window. Agent2Learn checks the session against LEARN before saving the minimum scoped API session. Your password is never requested by the tool or typed by an agent.

## Why keep a dedicated profile?

The separate profile can retain Waterloo and Duo's remembered-login state. It keeps ordinary browsing separate and can reduce repeated sign-in prompts. The API session lives in your operating system's keyring, with a permission-restricted file fallback when no keyring is available.

The profile and session are machine state, outside your vault. **Sign in independently on each device.** Never copy cookies, a profile, or a session file to another machine or into chat.

## Check without opening the browser

```bash
a2l auth --check
```

This contacts LEARN to validate the saved session. It does not launch a browser or ask for cookies.

## When the session expires

An expired session exits with **code 75**. Run `a2l auth`, complete sign-in, and retry the command that stopped.

Expiry is expected. It does not mean your local vault is damaged.

## If browser sign-in is unavailable

```bash
a2l auth --paste
```

This is a supported alternative with hidden input in your own terminal. Use the session from your own browser on the same device. Nothing should be pasted into chat, a command argument, an issue, or a support file.

During browser sign-in, the tool permits only the LEARN origin and the school adapter's declared identity-provider boundaries. An unexpected page or iframe host stops sign-in; an optional subresource is blocked locally.

The Waterloo identity-host list is documented as provider-boundary reasoning. Live Windows and Linux same-device validation remain release gates. A blocked hostname can be reported without sharing session material; see the [detailed authentication record](https://github.com/ManagementMO/agent2learn/blob/main/docs/AUTHENTICATION.md).

## Clear sign-in state

```bash
a2l auth --clear-profile
```

After your confirmation, this removes the dedicated profile and saved API session, including the keyring and file fallback. It also removes that profile's remembered-login state. Your course vault remains on disk.

If you need help, run `a2l doctor` first. Share only the redacted `a2l doctor --report` output, never credentials, profiles, cookies, or real course files.
