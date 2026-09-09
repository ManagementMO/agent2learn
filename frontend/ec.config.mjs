// Both Markdown fences and the dynamic installation commands use this renderer.
// Hooks live here so Astro can also load them for Starlight's Code component.
export default {
  themes: ['github-light', 'github-dark'],
  defaultProps: { frame: 'none' },
  styleOverrides: {
    borderRadius: '0.5rem',
    borderColor: 'var(--line)',
    codeBackground: 'var(--surface)',
    codeFontFamily: 'var(--font-mono)',
    codeFontSize: '0.8125rem',
    codeLineHeight: '1.8',
    codePaddingBlock: '1.125rem',
    codePaddingInline: '1rem',
    frames: {
      frameBoxShadowCssValue: 'none',
      inlineButtonForeground: 'var(--muted)',
      inlineButtonBorder: 'var(--line)',
      inlineButtonBorderOpacity: '1',
      inlineButtonBackgroundHoverOrFocusOpacity: '0.08',
      tooltipSuccessBackground: 'var(--ink)',
      tooltipSuccessForeground: 'var(--paper)',
    },
  },
  plugins: [
    {
      name: 'Accessible code example labels',
      hooks: {
        postprocessRenderedBlock: ({ codeBlock, renderData }) => {
          // Name keyboard-scrollable examples in the static HTML. Installation
          // components have explicit titles; Markdown examples use their order.
          const index = codeBlock.parentDocument?.positionInDocument?.groupIndex ?? 0;
          const label = codeBlock.props.title || `Code example ${index + 1}`;
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
};
