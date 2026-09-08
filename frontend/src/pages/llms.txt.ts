import { getCollection } from 'astro:content';
import { repository, release } from '../lib/site';

export async function GET() {
  const entries = (await getCollection('docs', ({ id }) => id.startsWith('docs/'))).sort((a, b) =>
    a.id.localeCompare(b.id),
  );
  const text = [
    '# Agent2Learn',
    '> A local course vault for your own Waterloo LEARN account. Original files, Markdown twins, and inspectable source citations. No hosted course storage or product telemetry. Grades and discussions are off by default. Uploads are disabled in this build. The evidence scan does not establish correctness or policy compliance.',
    release.published
      ? `PyPI release: ${release.version}.`
      : 'PyPI release coming soon. Do not run a package installer before the official package is available.',
    '## Start here',
    '- [Setup prompt](/agent-prompt.txt): instructions an agent can use to prepare setup and hand interactive onboarding to the user.',
    '## Documentation',
    ...entries.map(
      (entry) => `- [${entry.data.title}](/${entry.id}/): ${entry.data.description ?? ''}`,
    ),
    '## Canonical sources',
    `- [Repository](${repository}): Python engine, source documentation, release gates, and canonical skills.`,
    `- [Agent Skills](${repository}/tree/main/skills): a2l-setup, a2l-sync, a2l-study, and a2l-coursework.`,
  ].join('\n\n');
  return new Response(`${text}\n`, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
}
