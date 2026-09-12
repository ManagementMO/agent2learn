// Starlight 0.42 observes a narrow reading band near the top of the viewport.
// Short final sections cannot always reach it before the document stops scrolling.
// Keep its normal tracking and accessible mobile menu; correct only that boundary.
interface StarlightToc extends HTMLElement {
  current: HTMLAnchorElement;
  getRootMargin(): string;
}

async function trackDocumentEnd() {
  const elements = [
    ...document.querySelectorAll<StarlightToc>('starlight-toc, mobile-starlight-toc'),
  ];
  await Promise.all(elements.map((toc) => customElements.whenDefined(toc.localName)));
  const tocs = elements.map((toc) => ({
    toc,
    sections: [...toc.querySelectorAll<HTMLAnchorElement>('a[href^="#"]')]
      .map((link) => ({
        link,
        heading: document.getElementById(decodeURIComponent(link.hash.slice(1))),
      }))
      .filter((section) => section.heading !== null),
  }));
  if (!tocs.length) return;
  const main = document.querySelector('main');

  let wasAtEnd = false;
  const update = () => {
    const root = document.documentElement;
    // The main's empty bottom padding grows with viewport height. WebKit can
    // resize into that space without updating scrollY, so use the content end.
    // Allow rounding between scrollHeight and fractional scrollY, while keeping
    // a non-scrollable page at Overview.
    const bottomPadding = main ? parseFloat(getComputedStyle(main).paddingBottom) : 0;
    const remaining = root.scrollHeight - root.clientHeight - window.scrollY - bottomPadding;
    const atEnd = window.scrollY > 2 && remaining <= 2;
    for (const { toc, sections } of tocs) {
      let section = atEnd ? sections.at(-1) : undefined;
      if (!atEnd && wasAtEnd) {
        // A small upward scroll may not cross an observer threshold. Restore the
        // heading at Starlight's own reading line, including its mobile offset.
        const readingLine = -parseFloat(toc.getRootMargin());
        section = sections[0];
        for (const candidate of sections) {
          if (candidate.heading!.getBoundingClientRect().top <= readingLine + 1) {
            section = candidate;
          }
        }
      }
      if (section && !section.link.hasAttribute('aria-current')) {
        // Use Starlight's setter so its stored selection and the mobile summary
        // stay in sync. Changing aria-current alone would leave stale state.
        toc.current = section.link;
      }
    }
    wasAtEnd = atEnd;
  };

  let frame = 0;
  const schedule = () => {
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      update();
    });
  };
  window.addEventListener('scroll', schedule, { passive: true });
  window.addEventListener('resize', schedule);
  window.addEventListener('pageshow', schedule);
  window.addEventListener('hashchange', schedule);

  // Native intersections can arrive after the last scroll frame or the resize
  // debounce. Reconcile them before paint; the attribute guard prevents a loop.
  const selectionObserver = new MutationObserver(update);
  for (const { toc } of tocs) {
    selectionObserver.observe(toc, {
      subtree: true,
      attributes: true,
      attributeFilter: ['aria-current'],
    });
  }
  if (main) new ResizeObserver(schedule).observe(main);
  update();
}

void trackDocumentEnd();
