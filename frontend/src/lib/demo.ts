/** Original synthetic material shared by the homepage and documentation. */
export const demoFiles = [
  {
    id: 'index',
    name: 'INDEX.md',
    shortName: 'Index',
    folder: 'DEMO 101',
    lines: [
      '# DEMO 101',
      'Foundations of modelling',
      '',
      '## Course material',
      '- Week 3 / Linear models',
      '',
      '## Assignments',
      '- Problem Set 1',
      '',
      'Start here. Follow the source files.',
    ],
  },
  {
    id: 'linear',
    name: 'Linear models.md',
    shortName: 'Lecture',
    folder: 'content / Week 3',
    lines: [
      '# Linear models',
      '',
      '## Feasible solutions',
      'A feasible solution satisfies every',
      'constraint in the model.',
      '',
      'The objective selects the best feasible',
      'solution for the quantity being modelled.',
      '',
      '## Next: the graphical method',
    ],
  },
  {
    id: 'prompt',
    name: 'instructions.md',
    shortName: 'Assignment',
    folder: 'assignments / Problem Set 1',
    lines: [
      '# Problem Set 1',
      '',
      '## Before you begin',
      'Read the linear models lecture.',
      '',
      '## Your task',
      'Identify the decision variables.',
      'Write each constraint in your model.',
      'Explain what makes a solution feasible.',
      '',
      'Cite the course material you use.',
    ],
  },
] as const;

const lecture = demoFiles[1];
const start = 4;
const end = 5;
export const demoCitation = {
  file: lecture.name,
  path: `${lecture.folder.replaceAll(' / ', '/')}/${lecture.name}`,
  range: `${start}–${end}`,
  label: `${lecture.name}:${start}–${end}`,
  start,
  end,
  lines: lecture.lines.slice(start - 1, end),
};
