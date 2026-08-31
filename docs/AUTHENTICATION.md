# Authentication

Agent2Learn never asks for your password and never types it for you. You sign in yourself, in a
real browser, on your own machine. Agent2Learn then borrows the resulting LEARN API session — and
only that.

## How `a2l auth` works

`a2l auth` launches a **dedicated** Chrome or Edge profile, separate from your everyday browser
profile, stored under Agent2Learn's own state directory. You complete WatIAM sign-in and Duo in
that window. Agent2Learn then reads the LEARN cookies it needs, verifies them against LEARN's own
"who am I" endpoint, and saves the minimum scoped projection.

Why a dedicated profile:

- Your normal browsing, cookies for unrelated sites, history, and extensions are never touched.
- Duo's **"remember this device"** works, so you are not re-prompted on every sync. That state
  lives in this profile, which is exactly why the profile is worth keeping and exactly why you
  should not copy it anywhere.
- Clearing it is one command and affects nothing else.

Only cookies scoped to the LEARN origin are read. Requests to hosts the school adapter has not
declared for sign-in are blocked during the interactive window. For Waterloo the adapter permits
the LEARN origin, the boundary-matched `duosecurity.com` provider domain, and the Waterloo ADFS
hand-off `adfs.uwaterloo.ca`, each over HTTPS on the default port. `duosecurity.com` is a
whole-provider boundary: it absorbs Duo's changing tenant and asset subdomains rather than naming
hosts that move, at the cost of covering every Duo tenant and not only Waterloo's. Unrelated
registrable domains are not permitted, and Microsoft hosts are not guessed — if a sign-in path
reaches a host the adapter has not declared, the flow stops and reports only that hostname for
review.

This list is provider-boundary reasoning, not a published record of hosts captured from a live
sign-in, and it has not yet been exercised against a real instance on Windows or Linux. Confirming
it is part of the same-device authentication release gate; until then, treat an unexpected blocked
hostname as information to report rather than as a defect in your setup, and use `--paste`.

Unknown page subresources are still denied at the Fetch boundary. A blocked document or iframe
stops the sign-in immediately; a blocked optional request such as an analytics beacon is failed
locally so it cannot egress or terminate an otherwise valid sign-in. The authoritative whoami
check remains required, so a blocked request that the sign-in actually needs cannot produce a
saved session.

## Where the session is stored

Agent2Learn stores the session in your operating system's keyring when one is available. When no
keyring backend exists — common on minimal Linux installs — it falls back silently to a
permission-restricted file in Agent2Learn's state directory. `a2l doctor` tells you which backend
is in use.

The stored projection is deliberately minimal: the cookies the API needs, the LEARN base URL, and
the CSRF token. It is not a copy of your browser profile.

## Same device, always

The session is bound in practice to the machine and browser that produced it.

**Never copy a browser profile, a cookie value, or a session file between machines**, and never
paste one into a chat, an issue, a pull request, or a support request. Doing so hands over live
access to your student account, including anything your account can reach. Agent2Learn's own
diagnostics are built to make this hard to do by accident: the shareable `a2l doctor --report` is
an allowlist that cannot emit session material.

If you use more than one computer, run `a2l auth` separately on each. That is the intended
workflow, not a limitation to work around.

## `--paste`, a first-class path

Some environments cannot launch a browser: a headless server, a locked-down lab machine, a remote
session without a display.

```bash
a2l auth --paste
```

This prompts for the session value with **hidden input** — nothing is echoed to your terminal and
nothing lands in your shell history. Get the value from your own browser's developer tools on the
same machine you are signed in on. This is a supported path, not a workaround.

## When the session expires

LEARN sessions expire. Agent2Learn detects this specifically rather than treating it as a generic
failure: an unauthenticated LEARN API call answers with an HTML login page, which is what the
expiry detector looks for.

An expired session exits with **code 75** and tells you to run `a2l auth`. If you script
Agent2Learn, treat 75 as "re-authenticate", not as "the command is broken".

```bash
a2l auth --check     # verify the saved session without launching a browser
```

## Clearing

```bash
a2l auth --clear-profile
```

This removes the dedicated browser profile **and** the saved session from both the keyring and the
file fallback. You will re-do WatIAM and Duo next time, including the "remember this device"
prompt, because that state lived in the profile you just deleted.

Keep the profile if you want fewer Duo prompts. Clear it if you are handing the machine on, if you
suspect the profile has been tampered with, or if you simply want no local sign-in state.

## Recovery, without sending anyone your credentials

Work through these in order.

1. **`a2l doctor`.** It names exactly one next action. Start there.
2. **Exit code 75, or "session expired":** run `a2l auth`.
3. **Sign-in window opens but never completes:** finish Duo inside *that* window, not your normal
   browser. If Duo appears to hang, close the window, run `a2l auth --clear-profile`, then
   `a2l auth` again.
4. **No browser available, or the launch fails:** use `a2l auth --paste`.
5. **`a2l auth --check` says the session is valid but sync fails:** the problem is not
   authentication. Run `a2l doctor` and read the coverage report; a blocked licensed resource or a
   conversion gap is not a sign-in problem.
6. **Suspected corrupt local state:** `a2l auth --clear-profile`, then `a2l auth`. Your vault is
   untouched by this.
7. **Still stuck:** open an issue with `a2l doctor --report` output only.

**Do not send maintainers your password, a cookie value, a session file, a browser profile, or an
unredacted screenshot.** No maintainer will ever ask for any of them, and any message that does is
not from this project. `a2l doctor --report` exists precisely so you can ask for help without
sending anything sensitive.
