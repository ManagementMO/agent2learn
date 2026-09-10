# A2L — Waterloo gold

`a2l-waterloo-gold.svg` is the editable master for the website and launch film.
It contains original, hand-drawn serif outlines for **A2L**, a raised **2**, and
a short chamfered gold underline. No font, raster image, network request or D2L
artwork is embedded in it.

The raised **2** uses an upright bowl, a substantial horizontal foot and a
vertical right terminal. It has no italic/skew transform. The **A**, **L**,
wordmark proportions and gold underline are unchanged by this refinement.

The visual reference is [D2L's preferred logo](https://www.d2l.com/newsroom/logo-guidelines/).
The gold is **#FFD54F**, Waterloo's primary web yellow/gold in the
[University palette](https://uwaterloo.ca/conrad-school-entrepreneurship-business/sites/default/files/uploads/files/c015596-conrad-logoguidelines-june2019-pr12.pdf),
page 22. This is Agent2Learn's independent identity, not an official university
or D2L logo, endorsement, affiliation or claim of trademark clearance.

## Rendering

- Master geometry: `viewBox="0 0 360 144"` (2.5:1).
- Light surfaces: ink **#161616**, gold **#FFD54F**.
- Dark surfaces: ink **#FFFFFF**, the **same gold**.
- Keep the proportions. Do not stretch, recolour the accent or use CSS inversion.
- `Mark.astro` inlines the same paths and sets the appropriate ink colour. The
  decorative mark is hidden from assistive technology because the adjacent
  Agent2Learn name labels the link or section.
- `npm run brand:build` generates light/dark SVGs and 1440px transparent PNGs,
  the favicon and 512px icon, and byte-identical light/dark film assets.
- `npm run brand:check` checks every export and film copy against the master;
  SVG exports record its SHA-256. The film manifest separately pins the selected
  light/dark assets. Review both hashes when intentionally editing the master.

The old `a2l-source.png` is preserved only as a historical master, not used by
the live website. The film's historical `editorial` and `frontend` variants
remain available for explicit comparison or rollback.
