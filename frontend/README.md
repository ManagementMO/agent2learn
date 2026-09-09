# Agent2Learn website

The standalone landing page and documentation site. Everything here builds to static files; it does not change, bundle, or replace the Python engine. Node.js is a website development dependency, not an Agent2Learn runtime requirement.

## Work locally

Use Node.js 22.12 or newer.

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:4321`. For the complete production search experience, build and preview:

```bash
npm run build
npm run preview
```

Pagefind indexes the production HTML during the build. Search is entirely local to the generated site; there is no search service or API key. Check search against the production preview, because the development server does not include the generated index.

## Where things live

| Path                                | Responsibility                                                                      |
| ----------------------------------- | ----------------------------------------------------------------------------------- |
| `src/pages/index.astro`             | The concise landing page.                                                           |
| `src/content/docs/docs/`            | Eleven user guides and reference pages, written in Markdown/MDX.                    |
| `src/components/VaultDemo.astro`    | The interactive, explicitly synthetic course example.                               |
| `src/components/FeatureStory.astro` | Small product illustrations for original files, citations, and preserved revisions. |
| `src/components/DemoVideo.astro`    | Optional, user-controlled video dialog; media loads only when opened.               |
| `src/components/FileIcon.astro`     | Distinct icons for the index, Markdown, assignment instructions, and original PDF.  |
| `src/components/Mark.astro`         | Shared, lightweight logo rendering at each display size.                            |
| `src/assets/brand/a2l-source.png`   | Unchanged, approved A2L master from the launch film, pinned by SHA-256.             |
| `public/brand/mark.svg`             | Self-contained SVG wrapper around the cropped, web-sized A2L raster artwork.        |
| `public/brand/icon.png`             | A 512px logo export; the UI uses the SVG.                                           |
| `public/brand/social-card.png`      | The 1200 by 630 sharing image, composed with the real synthetic vault.              |
| `scripts/render-social-card.js`     | Reproduce the sharing image from the local production preview with Playwright CLI.  |
| `public/favicon.svg`                | The A2L wordmark on a light tile, readable in light and dark browser chrome.        |
| `scripts/build-brand.mjs`           | Reproducible wordmark, favicon and icon exports; the build checks for drift.        |
| `src/styles/shared.css`             | Typography, common controls, and shared tokens.                                     |
| `src/styles/home.css`               | Responsive landing-page composition and both themes.                                |
| `src/styles/docs.css`               | The Starlight documentation theme.                                                  |
| `src/lib/site.ts`                   | Release status, install commands, repository URL, and the copied agent prompt.      |
| `src/lib/social.ts`                 | Shared Open Graph and large-image card metadata for the homepage and docs.          |
| `scripts/verify-build.mjs`          | Internal link, anchor, asset, and agent-export checks over the built output.        |

The site uses Astro, Starlight, shared paper/graphite/cobalt color tokens, DM Sans, and IBM Plex Mono. Dependencies are pinned in `package-lock.json`. Fonts are served locally; their license notices are included under `public/licenses/`. No analytics, remote font calls, or background network integrations are added.

The logo is the approved, image-generated editorial **A2L** wordmark from the launch film. The master is preserved byte-for-byte; the export script trims transparent padding and resizes it for web use without redrawing the lettering. The SVG files embed raster artwork and are not claimed to be vector masters. Interface and feature icons remain editable vectors and are not brand marks.

`Mark.astro` supplies the homepage header/footer, setup prompt, citation demo, and all documentation headers (including the 404 page). It reserves the wordmark's wide proportions and displays a white version via CSS inversion in dark mode and on the charcoal setup section. Mobile headers use a smaller optical size to preserve navigation space. The browser favicon and 512px icon use a light tile for a consistent silhouette in either browser theme.

After an approved master change, review its source hash in `scripts/build-brand.mjs`, run `npm run brand:build`, then rebuild and regenerate the sharing image below. `npm run brand:check` verifies that the checked-in exports still match the approved master; the normal build includes this gate. Do not edit generated SVGs or PNGs independently.

## Light and dark themes

The landing page starts with the system preference and has an explicit light/dark button. Its preference shares Starlight's `starlight-theme` local-storage key, so navigation between the landing page and docs preserves the selection. The docs also offer an Auto setting. Early theme initialization avoids a light flash on dark pages.

`ThemeColor.astro` keeps the browser's toolbar colour aligned with each page's header. It follows the resolved theme on both the homepage and documentation, including saved choices and automatic system changes. `DocsHead.astro` adds it alongside Starlight's default head metadata.

The layout uses white paper, cool gray surfaces, and graphite backgrounds. Cobalt identifies primary actions, source citations, focus rings, and the current documentation page. The palette lives in `shared.css`; dark mode has its own contrast-adjusted blue rather than an inverted light palette. The charcoal agent section keeps a consistent treatment in both themes.

File selection uses native radio inputs, prompt and mobile vault expansion use native disclosure controls, and the documentation uses Starlight's accessible search, tabs, navigation, and theme selector. Scrollable code examples have distinct accessible names. Copy failures show a local recovery message. Reduced-motion preferences are respected.

The desktop vault starts on the assignment instructions. Following its citation selects the lecture, focuses line 4, and highlights the source lines and corresponding file over 180ms. Choosing another file clears the citation state. Reduced-motion mode shows the result immediately.

On phones, the question, answer, and a source excerpt come first. The excerpt is generated from the same source lines as the full viewer. Following the citation expands the vault and focuses the source; **Back to answer** collapses the viewer and returns keyboard focus to the citation. The reader can also expand the vault independently. That disclosure choice survives viewport changes, and all three files remain available with compact mobile labels. Without JavaScript, the full vault stays expanded and native file selection remains usable.

## Optional demo video

Set `PUBLIC_DEMO_VIDEO_URL` to the final approved HTTPS video URL, or an origin-relative file path such as `/demo.mp4`, in the hosting build environment. `.env.example` documents both build settings. An unset value hides the entire **Watch the demo** action; there is no placeholder or release-pending message.

The native dialog loads its video and poster only after the viewer clicks Watch. It provides playback controls, Escape and close-button dismissal, focus return, and a direct-video link if playback fails. Closing the dialog pauses and unloads the video. The poster is a byte-identical copy of the tracked synthetic launch-film still at `videos/a2l-cinematic/renders/signalflow-agent-poster.png`. No video or soundtrack has been published or newly approved by this website change.

## Sharing image

`public/brand/social-card.png` is a static, 1200 by 630 PNG. The homepage and documentation include its absolute Open Graph and large-image card URLs when `SITE_URL` is configured. It shows only the synthetic example and contains no release-availability claim.

To regenerate it, keep the production preview running at `http://127.0.0.1:4321` and run these commands in a second terminal from `frontend/`:

```bash
npx @playwright/cli -s=a2l-art open http://127.0.0.1:4321/
npx @playwright/cli -s=a2l-art run-code --filename scripts/render-social-card.js
npx @playwright/cli -s=a2l-art close
```

The renderer reuses the built vault markup and bundled fonts. It changes only its isolated browser page while composing the image, then writes the PNG to `public/brand/`. Run `npm run build` afterward to copy the refreshed image into `dist/`.

## Publishing the website

The site is prepared with **`release.published: true`** for publication after the matching package is available on PyPI. The landing page, install guide, copied pages, and agent prompt use the standard installation flow.

Before deploying:

1. Confirm that the published package and the repository's installer pins are the versions you intend to advertise.
2. Keep `release.version` in `src/lib/site.ts` aligned with that package version.
3. Run `npm run build` and inspect installation, the copied agent prompt, and `/llms.txt` in the preview.
4. Set `SITE_URL` in the hosting build environment to the real HTTPS origin you choose. This enables canonical URLs, the sitemap, and the landing page's social image metadata. A local build without a domain intentionally skips the sitemap.

The shared release switch concerns **package availability only**. It cannot enable the engine's submission capability. Upload-related documentation must continue to match `src/agent2learn/_release.py` and the authoritative release gates.

Deploy `dist/` to a static host, using this folder as the project root and `npm run build` as the build command. The site expects deployment at an origin's root, not under a repository-name subpath. Serve `404.html` for unknown paths; do not rewrite every route to the landing page. No deployment has been configured or performed here.

## Documentation for agents

- Each guide has a **Copy page** button. It copies the title and full guide as Markdown, including all installation methods or the full setup prompt where applicable. The clipboard text comes from the existing guide and shared component data; there is no separate Markdown view or downloadable copy to maintain.
- `/llms.txt`: a lightweight index linking to the regular documentation pages.
- `/agent-prompt.txt`: the same setup prompt copied by the UI.

The website prompt is a handoff, not another canonical skill set. Keep the engine's four `skills/` directories as the source of installed skill instructions.

## Keep the copy grounded

The site's claims were traced through the authoritative release design and plan, `docs/LAUNCH.md`, the existing user documentation, the actual CLI, `pipeline.py`, source validation in `ground.py`, the four canonical skills, and the production-pipeline CLI regression.

When changing user-facing behavior, review the corresponding website page:

| Engine or source documentation                                | Website guide                                      |
| ------------------------------------------------------------- | -------------------------------------------------- |
| `docs/install.md`, `install.sh`, `install.ps1`, `cli.py:init` | Installation; for agents; shared install commands. |
| `pipeline.py`, `ingest.py`, `audit.py`                        | Your first sync; the vault; troubleshooting.       |
| `ground.py`, `skills/a2l-study`, `skills/a2l-coursework`      | Study with sources; the copied prompt.             |
| `check.py`                                                    | Scan a draft; command reference.                   |
| `docs/AUTHENTICATION.md`, `auth/`                             | Authentication; troubleshooting.                   |
| `docs/PRIVACY.md`, `privacy.py`                               | Privacy; collection defaults in landing-page copy. |
| `cli.py`, `_release.py`                                       | Commands; installation and upload status.          |

All courses, file contents, and citations in the interactive example are synthetic. It illustrates a workflow rather than presenting a recorded CLI or model result. Hash validation proves source identity and integrity; lexical matches never establish correctness or academic-policy compliance.

## Verify a change

```bash
npm run format:check
npm run build
npm run check:release
```

For the logo-specific browser regression, open the production preview with Playwright CLI,
then run `run-code --filename scripts/verify-brand-browser.js` in that session. It checks
the homepage and documentation at 320, 375, 768 and 1440px in both themes, including
image decoding, aspect ratio, theme treatment and mobile header spacing. Screenshots
are saved under `output/playwright/`.

In the same session, run `run-code --filename scripts/verify-site-browser.js` for the interaction and accessibility checks. It exercises citation focus, native keyboard file selection, mobile return and viewport changes, install/prompt/page copying, clipboard refusal, installation tabs, and production search. It runs axe checks over the homepage at five widths in both themes and four representative guides at phone and desktop widths in both themes. Both scripts use the origin of the open preview, so independent worktrees can use different ports.

The build runs Astro/TypeScript checks, freshly renders all static pages, creates the search index, verifies internal navigation and anchors, and checks the agent index, setup prompt, and code-example labels. `astro build --force` clears the content cache so changes to rendering hooks cannot leave stale documentation HTML. Browser checks should cover both themes, phone and desktop widths, file selection, citation focus, copy success/failure, docs search, tabs, and the mobile menu. Keep temporary screenshots and browser reports under the ignored `output/playwright/` folder.

`check:release` builds a disposable copy with package availability switched on, a reserved test origin, and an optional video URL. It checks the published installation copy, agent prompt, documentation release notice, agent index, social image metadata, canonical URL, sitemap, and the player's absence of initial media loading, then removes the copy. It leaves the real release setting and any running preview unchanged.

For a short student walkthrough, ask a few Waterloo students to describe what Agent2Learn does, follow a source citation in the demo, and find the installation or agent setup path. Let them explore without coaching and record where they hesitate. This checks comprehension and discoverability beyond the automated browser checks.

The frontend has its own package lock and ignored build/dependency folders. The root Python package, canonical skills, existing documentation, and release automation remain outside this website's build boundary.
