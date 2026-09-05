import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { SolutionPage } from '../pages/solution-page';
import { SolutionsPage } from '../pages/solutions-page';
import { findSection } from './sections';
import { findSolution, SOLUTION_LABEL, SOLUTIONS } from './solutions';

const KEBAB_SLUG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

function renderSolutionPage(slug: string) {
  return render(
    <MemoryRouter initialEntries={[`/solutions/${slug}`]}>
      <Routes>
        <Route path="/solutions/:solutionSlug" element={<SolutionPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function renderSolutionsPage() {
  return render(
    <MemoryRouter initialEntries={['/solutions']}>
      <Routes>
        <Route path="/solutions" element={<SolutionsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('solution copy model', () => {
  it('publishes exactly the eight solution shapes with unique kebab-case slugs', () => {
    expect(SOLUTIONS).toHaveLength(8);
    const slugs = SOLUTIONS.map((solution) => solution.slug);
    expect(new Set(slugs).size).toBe(8);
    for (const solution of SOLUTIONS) {
      expect(solution.slug).toMatch(KEBAB_SLUG);
    }
  });

  it('fills every copy field and carries at least one capability family', () => {
    const textFields = [
      'title',
      'shortName',
      'description',
      'audience',
      'situation',
      'friction',
      'transformation',
      'scenario',
      'implementation',
      'governance',
      'evidence',
    ] as const;
    for (const solution of SOLUTIONS) {
      for (const field of textFields) {
        expect(solution[field].trim(), `${solution.slug}.${field}`).not.toBe('');
      }
      expect(solution.capabilities.length).toBeGreaterThan(0);
      expect(new Set(solution.capabilities).size).toBe(solution.capabilities.length);
    }
  });

  it('labels every scenario with the canonical SOLUTION_LABEL', () => {
    expect(SOLUTION_LABEL).toBe('Illustrative product scenario');
    for (const solution of SOLUTIONS) {
      expect(solution.scenarioLabel).toBe(SOLUTION_LABEL);
    }
  });

  it('frames every scenario as an illustrative product scenario, never a measured result', () => {
    for (const solution of SOLUTIONS) {
      expect(solution.scenario.toLowerCase()).toContain('illustrative product scenario');
    }
  });

  it('resolves each slug through findSolution and returns undefined for unknown slugs', () => {
    for (const solution of SOLUTIONS) {
      expect(findSolution(solution.slug)).toBe(solution);
    }
    expect(findSolution('not-a-real-solution')).toBeUndefined();
  });
});

describe('solution deep page', () => {
  it('renders a not-found heading for an unknown solution slug', () => {
    renderSolutionPage('not-a-real-solution');
    expect(screen.getByRole('heading', { level: 1, name: 'Page not found' })).toBeInTheDocument();
  });

  it('renders a known solution with its title, scenario label, and a back link to /solutions', () => {
    const record = SOLUTIONS[0];
    expect(record).toBeDefined();
    if (record === undefined) return;

    renderSolutionPage(record.slug);
    expect(screen.getByRole('heading', { level: 1, name: record.title })).toBeInTheDocument();
    expect(screen.getAllByText(SOLUTION_LABEL).length).toBeGreaterThan(0);

    const backLinks = screen
      .getAllByRole('link')
      .filter((link) => link.getAttribute('href') === '/solutions');
    expect(backLinks.length).toBeGreaterThan(0);
  });
});

describe('solutions landing page', () => {
  it('renders the /solutions hero title and one explorer card link per solution', () => {
    const section = findSection('/solutions');
    expect(section).toBeDefined();
    if (section === undefined) return;

    renderSolutionsPage();

    expect(
      screen.getByRole('heading', { level: 1, name: section.title }),
    ).toBeInTheDocument();

    const explorerHrefs = screen
      .getAllByRole('link')
      .map((link) => link.getAttribute('href'))
      .filter((href): href is string => href !== null && href.startsWith('/solutions/'));

    const expected = new Set(SOLUTIONS.map((solution) => `/solutions/${solution.slug}`));
    expect(new Set(explorerHrefs)).toEqual(expected);
  });
});
