/** Shared by the landing page and Starlight, once a real site origin is set. */
export function socialHead(site: string | URL | undefined): Array<{
  tag: 'meta';
  attrs: Record<string, string>;
}> {
  if (!site) return [];
  const image = new URL('/brand/social-card.png', site).href;
  const alt =
    'Agent2Learn: Your courses. Ready for your agent. A synthetic course vault with highlighted source lines.';
  return [
    { tag: 'meta', attrs: { property: 'og:image', content: image } },
    { tag: 'meta', attrs: { property: 'og:image:type', content: 'image/png' } },
    { tag: 'meta', attrs: { property: 'og:image:width', content: '1200' } },
    { tag: 'meta', attrs: { property: 'og:image:height', content: '630' } },
    { tag: 'meta', attrs: { property: 'og:image:alt', content: alt } },
    { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
    { tag: 'meta', attrs: { name: 'twitter:image', content: image } },
    { tag: 'meta', attrs: { name: 'twitter:image:alt', content: alt } },
  ];
}
