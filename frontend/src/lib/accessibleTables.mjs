// Starlight makes wide tables scrollable. Explicit keyboard focus also works
// in Firefox and without JavaScript; the preceding heading names the table.
export function accessibleTables() {
  let section = 'Documentation';
  return {
    name: 'a2l-accessible-tables',
    element: {
      filter: ['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table'],
      visit(node, context) {
        if (node.tagName !== 'table') {
          section = context.textContent(node).trim() || section;
          return;
        }
        context.setProperty(node, 'tabindex', 0);
        if (
          !node.properties['aria-label'] &&
          !node.properties['aria-labelledby'] &&
          !node.children.some((child) => child.tagName === 'caption')
        )
          context.setProperty(node, 'aria-label', section);
      },
    },
  };
}
