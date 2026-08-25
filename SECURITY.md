# Security policy

Agent2Learn runs on a student's own machine, against their own university account, holding a live
LEARN session. Security reports are taken seriously and handled privately.

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Use GitHub's private vulnerability reporting on this repository:
**Security → Report a vulnerability**
(<https://github.com/ManagementMO/agent2learn/security/advisories/new>)

Please include what you can of: affected version (`a2l --version`), operating system, the behaviour
observed, and the smallest reproduction you have. **Never include a real session cookie, browser
profile, student identifier, grade, or course file** — a redacted description is always sufficient
to start, and `a2l doctor --report` produces a diagnostic that is redacted by design.

Expect an acknowledgement within **7 days** and an assessment within **30 days**. If a fix is
warranted, we will agree a disclosure timeline with you and credit you in the release notes unless
you prefer otherwise.

## Supported versions

Agent2Learn is pre-release. Only the **latest published version** receives security fixes; there are
no long-term support branches. Once v0.1.0 is released, this section will state the supported
minor series explicitly.

| Version | Supported |
| --- | --- |
| `main` (unreleased) | ✅ |
| everything else | ❌ |

## What is in scope

- Leakage of session cookies, tokens, browser-profile contents, or the XSRF token — into logs,
  `a2l doctor` output, error messages, generated vault files, or the terminal.
- Any path that performs a **mutating** LEARN request without the specified per-file interactive
  human confirmation, or any bypass of `a2l enable-submit`.
- Any path that fetches a **licensed third-party** resource (eTextbook, LTI target, publisher link)
  that the design says must remain a link stub, or that follows a redirect off the egress allowlist.
- Path traversal, zip-slip, zip-bomb, or symlink escape during archive inspection or vault writes.
- Execution of anything found in course material — notebook cells, Office macros, embedded PDF
  actions, scripts.
- **Prompt injection that causes an agent to take an action**, rather than merely quote the text.
  Course files are untrusted data; a PDF telling an agent to reveal a secret or run a command must
  be cited, never obeyed.
- Writing outside the vault and the documented per-user application directories.

## What is out of scope

- Vulnerabilities in D2L Brightspace, Waterloo LEARN, WatIAM, or Duo. Report those to the vendor or
  to `learnhelp@uwaterloo.ca`.
- Anything requiring an attacker who already has local access to the user's account or unlocked
  machine — the session is deliberately reusable on that device by design.
- Denial of service against the user's own LEARN account through their own configuration.
- Missing hardening that is documented as a deliberate, recorded trade-off in the design spec.

## Design commitments relevant to security

- **No Agent2Learn server, account system, or telemetry.** The only non-LEARN request is an explicit
  `a2l upgrade --check`.
- **Credentials never leave the device.** No password is ever requested or stored; browser profiles
  and session exports are never copied between machines, including for testing or support.
- **Secrets are never printed, logged, or committed** — not in errors, not under `--verbose`, and
  not in `doctor --report`, which uses an allowlist after redaction.
- **Mutating requests are never retried automatically**, and there is no `--yes`, `--force`,
  environment-variable, or piped-stdin bypass of a submission confirmation.
- **Mutating redirects are never followed automatically.** A 301/302/303/307/308 response after a
  POST is surfaced for the caller to decide, so a submission body cannot be silently replayed at a
  second location.
- Secret scanning (`detect-secrets` pre-commit, gitleaks in CI) supplements — and does not replace —
  fixture allowlisting and human review.
