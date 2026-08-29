#!/usr/bin/env bash
# Agent2Learn installer for macOS and Linux.
#
# It installs one pinned Agent2Learn release with uv, verifies the command, and — only when a real
# terminal is on both ends — hands straight to interactive onboarding. Onboarding is what asks
# before writing anything: this script never creates a vault, an agent skills directory, or a
# browser profile, and it never needs administrator rights.
#
# Everything it installs is pinned in the constants block below. There is deliberately no flag or
# environment variable for pointing it at another package, index, or URL: a one-line installer that
# can be aimed anywhere is an attack surface, not a convenience.
set -euo pipefail

# ---- reviewed constants ---------------------------------------------------------------
UV_VERSION="0.12.5"
A2L_VERSION="0.1.0"
# ---------------------------------------------------------------------------------------

UV_INSTALLER="https://astral.sh/uv/${UV_VERSION}/install.sh"

say() { printf '%s\n' "$*"; }
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }

# Compare dotted numeric versions without sort -V, which BSD and GNU disagree about.
version_at_least() {
    local have="$1" want="$2" index have_part want_part
    local -a have_parts want_parts
    IFS='.' read -r -a have_parts <<< "$have"
    IFS='.' read -r -a want_parts <<< "$want"
    for index in 0 1 2; do
        have_part="${have_parts[index]:-0}"
        want_part="${want_parts[index]:-0}"
        if ((10#$have_part > 10#$want_part)); then return 0; fi
        if ((10#$have_part < 10#$want_part)); then return 1; fi
    done
    return 0
}

detect_uv_version() {
    local raw
    raw="$(uv --version 2>/dev/null || true)"
    # "uv 0.12.5 (abcdef 2026-01-01)" -> "0.12.5"
    printf '%s' "$raw" | sed -n 's/^uv[[:space:]]\{1,\}\([0-9][0-9.]*\).*/\1/p'
}

main() {
    local existing="" existing_raw="" needs_uv=1

    if command -v uv > /dev/null 2>&1; then
        existing_raw="$(uv --version 2>/dev/null || true)"
        existing="$(detect_uv_version)"
        if [ -z "$existing" ]; then
            fail "found uv but could not read its version from: ${existing_raw:-<no output>}
Install the tested version yourself, then rerun this installer:
  curl -fsSL ${UV_INSTALLER} | sh"
        fi
        if version_at_least "$existing" "$UV_VERSION"; then
            needs_uv=0
        fi
    fi

    say "Agent2Learn installer"
    say ""
    say "This will:"
    if [ "$needs_uv" -eq 1 ]; then
        if [ -n "$existing" ]; then
            say "  - replace uv ${existing} with the tested uv ${UV_VERSION} from ${UV_INSTALLER}"
        else
            say "  - install uv ${UV_VERSION} from ${UV_INSTALLER}"
        fi
    else
        say "  - reuse the uv ${existing} already on your PATH"
    fi
    say "  - install agent2learn==${A2L_VERSION} as a uv tool"
    say "  - add the uv tool directory to your shell PATH"
    say "  - verify that a2l runs"
    say ""
    say "It does not create a vault, install agent skills, open a browser, or use sudo."
    say ""

    if [ "$needs_uv" -eq 1 ]; then
        local installer
        installer="$(mktemp)"
        # Download first, then run, so the fetched bytes are a file we could inspect rather than
        # an unnamed pipe straight into a shell.
        curl -fsSL "$UV_INSTALLER" -o "$installer" \
            || fail "could not download the uv installer from ${UV_INSTALLER}"
        sh "$installer" || { rm -f "$installer"; fail "the uv installer did not complete"; }
        rm -f "$installer"
        hash -r 2>/dev/null || true
    fi

    command -v uv > /dev/null 2>&1 || fail "uv is still not on PATH after installation"

    say "installing agent2learn==${A2L_VERSION}"
    uv tool install "agent2learn==${A2L_VERSION}"
    uv tool update-shell || true

    local tool_bin
    tool_bin="$(uv tool dir --bin)"
    [ -n "$tool_bin" ] || fail "uv did not report its tool executable directory"
    PATH="${tool_bin}:${PATH}"
    export PATH

    local reported
    reported="$(a2l --version 2>/dev/null || true)"
    case "$reported" in
        *"${A2L_VERSION}"*) : ;;
        "") fail "a2l did not run after installation" ;;
        *) fail "expected agent2learn ${A2L_VERSION} but a2l reported: ${reported}" ;;
    esac
    say "verified: ${reported}"
    say ""

    if [ -t 0 ] && [ -t 1 ]; then
        say "starting setup; it will preview and ask before writing anything"
        exec a2l init
    fi

    say "Installed. Onboarding is interactive, so finish it yourself:"
    say "run in a terminal: a2l init"
}

main "$@"
