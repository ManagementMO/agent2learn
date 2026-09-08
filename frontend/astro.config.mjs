import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import tailwindcss from '@tailwindcss/vite';
import { socialHead } from './src/lib/social.ts';

// Set SITE_URL only when the owner chooses a real deployment origin.
// Building this static website neither publishes the package nor enables uploads.
export default defineConfig({
  site: process.env.SITE_URL || undefined,
  trailingSlash: 'always',
  vite: { plugins: [tailwindcss()] },
  integrations: [
    starlight({
      title: 'Agent2Learn',
      description: 'Your Waterloo courses, as local files your agent can read and cite.',
      head: socialHead(process.env.SITE_URL),
      favicon: '/favicon.svg',
      defaultLocale: 'root',
      locales: { root: { label: 'English', lang: 'en' } },
      customCss: ['./src/styles/docs.css'],
      components: {
        Head: './src/components/DocsHead.astro',
        PageTitle: './src/components/DocsPageTitle.astro',
        SiteTitle: './src/components/DocsTitle.astro',
      },
      social: [
        { icon: 'github', label: 'GitHub', href: 'https://github.com/ManagementMO/agent2learn' },
      ],
      editLink: {
        baseUrl: 'https://github.com/ManagementMO/agent2learn/edit/main/frontend/',
      },
      expressiveCode: {
        themes: ['github-light', 'github-dark'],
        styleOverrides: { borderRadius: '0.625rem' },
        plugins: [
          {
            name: 'Accessible code example labels',
            hooks: {
              postprocessRenderedBlock: ({ codeBlock, renderData }) => {
                // Expressive Code makes overflowing examples keyboard-scrollable.
                // Give those regions distinct names, already present in static HTML.
                const index = codeBlock.parentDocument?.positionInDocument?.groupIndex ?? 0;
                const label = `Code example ${index + 1}`;
                const namePre = (node) => {
                  if (node.type === 'element' && node.tagName === 'pre') {
                    node.properties.ariaLabel = label;
                  }
                  for (const child of node.children ?? []) namePre(child);
                };
                namePre(renderData.blockAst);
              },
            },
          },
        ],
      },
      sidebar: [
        {
          label: 'Start here',
          items: [
            { label: 'Introduction', slug: 'docs/introduction' },
            { label: 'Installation', slug: 'docs/installation' },
            { label: 'For agents', slug: 'docs/for-agents' },
          ],
        },
        {
          label: 'Use your vault',
          items: [
            { label: 'Your first sync', slug: 'docs/sync' },
            { label: 'Study with sources', slug: 'docs/study' },
            { label: 'Scan a draft', slug: 'docs/evidence-scan' },
            { label: 'The vault', slug: 'docs/vault' },
          ],
        },
        {
          label: 'Reference',
          items: [
            { label: 'Commands', slug: 'docs/commands' },
            { label: 'Authentication', slug: 'docs/authentication' },
            { label: 'Privacy', slug: 'docs/privacy' },
            { label: 'Troubleshooting', slug: 'docs/troubleshooting' },
          ],
        },
      ],
    }),
  ],
});
