import { agentPrompt, installMethods, release, releaseNotice } from './site';

/** Build clipboard text from the same source as the guide, without a separate page or export. */
export function copyPageText(title: string, body: string): string {
  const expansions: Record<string, string> = {
    ReleaseNote: release.published
      ? ''
      : `> **${releaseNotice.title}** ${releaseNotice.description}`,
    InstallCommands: installMethods
      .map(
        ({ label, description, command, language }) =>
          `### ${label}\n\n${description}\n\n\`\`\`${language}\n${command}\n\`\`\``,
      )
      .join('\n\n'),
    AgentPrompt: `\`\`\`text\n${agentPrompt}\n\`\`\``,
  };
  // These MDX components contain real guide content. Expand them from their
  // shared data so copying includes all install methods and the complete prompt.
  const content = body
    .replace(
      /^import\s+(?:ReleaseNote|InstallCommands|AgentPrompt)\s+from\s+['"][^'"]+['"];?\s*$/gm,
      '',
    )
    .replace(
      /<(ReleaseNote|InstallCommands|AgentPrompt)\b[^>]*\/>/g,
      (_, name: string) => expansions[name],
    );
  return `# ${title}\n\n${content.trim()}\n`;
}
