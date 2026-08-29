# Porting Agent2Learn to another school

The sync engine is institution-agnostic. Everything school-specific lives behind one protocol, so
adding a Brightspace institution means writing a small adapter — not touching transport,
conversion, indexing, or the vault.

This is the expansion pipeline document. `src/agent2learn/schools/uwaterloo.py` is the worked
reference; read it alongside this page.

## The `School` protocol

Defined in `src/agent2learn/schools/_base.py`. An adapter must provide every member below.

### Attributes

| Member | Type | Meaning |
| --- | --- | --- |
| `id` | `str` | Stable lowercase identifier, e.g. `uwaterloo`. Written into config; changing it later breaks existing installs. |
| `name` | `str` | Human-readable institution name for output. |
| `base_url` | `str` | The LEARN/Brightspace origin. Every request is confined to this origin; an off-origin target is refused rather than followed. |
| `timezone` | `str` | IANA zone, e.g. `America/Toronto`. Deadlines are rendered with explicit arithmetic in this zone — never in the machine's local time, and never naively. |
| `auth_hint` | `str` | One short sentence telling the user what sign-in will look like, e.g. which identity provider appears. |

### Methods

| Member | Returns | Contract |
| --- | --- | --- |
| `term_from_offering(code)` | `str \| None` | Extract the institution's term code from an offering code when one is present. Return `None` rather than guessing; a wrong term silently files a course in the wrong folder. |
| `term_label(term)` | `str` | Stable display label for a term code, e.g. `1265` → `Spring 2026`. Must be deterministic: it appears in vault paths and generated reports. |
| `auth_hosts()` | `list[str]` | Identity hosts allowed **only** during the interactive sign-in window. Keep it minimal; every entry is a host the browser may reach while a session is being established. |
| `outline_hosts()` | `list[str]` | First-party hosts allowed for outline rendering. First-party only. A third-party or licensed host here would turn outline rendering into an unwanted fetch. |
| `topic_exclusion_policy()` | `TopicExclusionPolicy` | Structured rules identifying licensed and external topics that must never be downloaded. |

### `TopicExclusionPolicy`

Three independent matchers, any of which excludes a topic:

- `kinds` — normalised topic kinds, e.g. `lti`.
- `host_suffixes` — matched at DNS-label boundaries, so `example.vitalsource.com` matches
  `vitalsource.com` while `notvitalsource.com` does not.
- `url_markers` — substrings such as `quicklink.d2l` or `type=lti`.

Start from `CONSERVATIVE_TOPIC_EXCLUSION_POLICY` and widen only with evidence. **Err toward
excluding.** A false exclusion costs the user one manual click in LEARN; a false inclusion
downloads licensed content the project promised never to touch.

## Writing an adapter

1. Create `src/agent2learn/schools/<yourschool>.py` and implement every member above.
2. **Leave `auth_hosts()` and `outline_hosts()` empty until you have real evidence.** Waterloo's
   own allowlists stayed empty until redacted same-device host evidence was reviewed. Guessing a
   host list is how a browser window ends up permitted to reach somewhere nobody vetted.
3. Register the adapter and add its `id` to the config validation.
4. Never hardcode API versions. `GET /d2l/api/versions/` is discovered at runtime by
   `calibrate.py`, and instances differ. Waterloo reports `lp 1.62` / `le 1.96`, which is an
   observation, not a constant to copy.

## Testing a new adapter

The whole point of the fixture harness is that you can build and test an adapter with no account
and no network.

```bash
uv run pytest tests/test_schools.py -q      # protocol conformance and policy matching
uv run pytest -q                            # the full offline suite
```

Write these tests for your adapter:

1. **Term parsing** — real offering codes from your institution, plus codes with no term, which
   must return `None`.
2. **Term labels** — deterministic and stable; they end up in vault paths.
3. **Timezone rendering** — at least one deadline across a daylight-saving boundary.
4. **Exclusion policy** — one licensed topic that must be excluded, one ordinary file that must
   not, and one lookalike hostname (`notyourvendor.com`) that must not match a suffix rule.
5. **Host allowlists** — assert the exact expected lists, so widening them is a deliberate, visible
   change in a diff.

Then run against the **synthetic** fixture API (`tests/synthetic_api`) rather than a live instance.
It serves the same shapes as a real D2L instance, including the failure modes that matter: 404 for
a route that serves no topic, 200 with an empty collection for a category a course does not use,
and login-shaped HTML for an unauthenticated call. Add routes there in that spirit — returning the
wrong status hides real bugs, and a transient status will be retried five times with backoff.

## Before proposing an adapter

- Confirm a browser-harvested session authenticates a plain API call **on the same device** for
  your institution. This is the prerequisite the whole design rests on; verify it before writing
  much code.
- Confirm the licensed-content policy matches how your institution actually delivers e-resources.
- Do **not** include any real course, student, grade, or session data in tests, fixtures, issues,
  or pull requests. Use synthetic values only.

A non-Waterloo Brightspace instance is untested territory. `schools/_base.py` also provides a
warned generic adapter so exploration is possible, but a warned generic run is not a supported
configuration.
