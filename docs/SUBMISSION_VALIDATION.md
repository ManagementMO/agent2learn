# Supervised submission validation record

This is the release-gate procedure for the one Agent2Learn operation that mutates a student's
LEARN account. It is a human-run test plan, not an automated fixture and not evidence that the
current public build may upload. Keep [`SUBMISSION_AVAILABLE`](../src/agent2learn/_release.py)
`False` until this procedure has passed against the exact release candidate.

## What the API contract says

Brightspace documents both operations at the same current-user route:

```
POST /d2l/api/le/{version}/{orgUnitId}/dropbox/folders/{folderId}/submissions/mysubmissions/
GET  /d2l/api/le/{version}/{orgUnitId}/dropbox/folders/{folderId}/submissions/mysubmissions/
```

The GET returns a JSON array of `EntityDropbox` objects. Each object contains a user `Entity` and
`Submissions`; each submission contains `SubmissionDate`, `SubmittedBy`, and a `Files` array whose
file records include `FileName` and `Size`. The route is explicitly described as returning only
submissions made by the current user, and the documented status failures include 403 and 404.
See the [D2L Dropbox API reference](https://docs.valence.desire2learn.com/res/dropbox.html),
especially the `EntityDropbox` schema and the current-user GET/POST entries.

Agent2Learn treats that envelope as part of the proof, not as an optional convenience: a flat
submission-like list, a non-user entity, or a missing/mismatched `SubmittedBy` identifier yields
`verification_unknown`. There is no compatibility parser that could turn a surprising response
into a false current-user match.

The implementation deliberately uses this route for both POST and read-back. It does not fall
back to the broad `/submissions/` listing, a group route, or an undocumented `mypost` route.

## Preconditions

The tester must have all of the following before starting:

1. A Waterloo LEARN instance and a browser/API session authenticated on the same device. Do not
   copy cookies, browser profiles, credentials, or Duo state between devices.
2. The exact release-candidate checkout or wheel being evaluated, with its commit SHA recorded.
3. A course owner-approved, **individual, non-graded, non-production** Dropbox dedicated to this
   test. Do not use a graded folder, a group folder, a closed folder, a real assignment, or a
   folder containing another student's work.
4. One harmless synthetic file created solely for this test, for example:

   ```text
   agent2learn-supervised-upload.txt
   ```

   Its contents must not contain coursework, personal data, credentials, cookies, or a real
   submission. Record its byte size and SHA-256 before starting.

Do not run this procedure if the owner has not approved the destination. A refusal, an unavailable
sandbox, or an unsupported instance is a failed release gate, not a reason to enable uploads.

## Minimal procedure

Run from the configured vault directory so the command resolves the same local course metadata
that the release candidate will use:

```sh
cd /path/to/the/test-vault
a2l --version
a2l enable-submit
a2l submit COURSE-CODE "Approved Practice Upload" /path/to/agent2learn-supervised-upload.txt
```

`enable-submit` is only the local acknowledgement. It must not issue a network mutation. The
`submit` command must first print a complete preview naming the course, folder ID, exact file
name, byte size, SHA-256, POST endpoint, current-user read-back endpoint, and one-time phrase.

Stop and report a failure if the preview names a group Dropbox, a different folder, a broad
`/submissions/` read-back, an undocumented route, different bytes, or an absolute path in the
receipt fields. If a tool or agent is driving the terminal, return control to the human now.

At the final prompt, the human tester—not an agent, script, piped input, or retry—types the exact
phrase shown in the preview. The candidate must attempt at most one POST for this confirmation.

## PASS criteria

Record the POST and GET observations independently. Both sections must pass.

### POST

- Exactly one request is sent to the documented `submissions/mysubmissions/` POST endpoint.
- The request is a `multipart/mixed` body with the JSON RichText part first and the file part
  second, and includes an explicit top-level `Content-Length`.
- The filename, byte count, and SHA-256 of the uploaded file match the staged preview exactly.
- The request carries the session's CSRF protection and receives a successful 2xx response.
- No redirect replay, endpoint fallback, automatic retry, second confirmation, or group endpoint
  occurs.

### Read-back GET

- Exactly one GET is sent to the documented current-user `submissions/mysubmissions/` endpoint.
- That GET is one-shot: a transient response is not retried and a redirect is not followed into a
  different route. Either result is `verification_unknown`.
- The response is a 2xx JSON list with the documented `Entity` → `Submissions` → `Files` shape.
- Exactly one newly created record matches the approved folder, exact filename, and exact byte size.
- Its `SubmissionDate` is after the confirmation timestamp. A stale record, duplicate filename,
  missing timestamp, wrong user/entity, wrong folder, or size mismatch is **not** a pass.
- The command reports `verified` only after this match. The local receipt contains no cookie,
  response body, confirmation phrase, display name, or absolute path.

If POST succeeds but the GET is 403, 404, HTML, malformed, not a list, stale, ambiguous, or
otherwise unreadable, the correct result is `verification_unknown`. Do not retry by re-entering the
phrase. Inspect LEARN manually and leave the release capability disabled.

## What to record

Store the record privately with the release evidence. It should contain only:

- release-candidate commit SHA and packaged version;
- date/time and operating system (no browser profile or session material);
- redacted LEARN host and discovered `lp`/`le` versions;
- redacted course/folder identifiers and confirmation that the folder was non-graded and
  individual;
- synthetic filename, byte size, and SHA-256;
- POST status class, request-count result, and whether the multipart ordering/length checks passed;
- GET status class, response-shape result, match count, freshness result, and read-back byte-size
  result;
- the final Agent2Learn receipt status (`verified` or `verification_unknown`) and any safe error
  classification.

Never record cookies, CSRF values, authorization headers, browser profile paths, response bodies,
student names, student numbers, grades, discussions, or course material. A redacted record is
evidence of this one designated sandbox test only; it does not prove group submissions, closed
folders, large files, other institutions, or production readiness.
