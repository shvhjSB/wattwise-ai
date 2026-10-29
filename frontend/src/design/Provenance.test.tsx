import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DemoBanner, ProvenanceBadge } from './Provenance';

describe('ProvenanceBadge', () => {
  it.each([
    ['synthetic', 'Synthetic'],
    ['observed', 'Observed'],
    ['uploaded', 'Uploaded'],
  ] as const)('says %s in words, not colour alone', (kind, text) => {
    render(<ProvenanceBadge kind={kind} />);

    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.getByText('Data provenance:', { exact: false })).toBeInTheDocument();
  });

  it('explains synthetic data in its tooltip', () => {
    render(<ProvenanceBadge kind="synthetic" />);

    expect(screen.getByTitle(/not measurements from real buildings/i)).toBeInTheDocument();
  });
});

describe('DemoBanner', () => {
  it('warns when everything is synthetic', () => {
    render(<DemoBanner kinds={['synthetic']} />);

    const note = screen.getByRole('note', { name: 'Demo data' });
    expect(note).toHaveTextContent('Everything shown is synthetic');
    expect(note).toHaveTextContent('not real-world performance');
  });

  it('points to the badges when synthetic and observed data are mixed', () => {
    render(<DemoBanner kinds={['synthetic', 'observed']} />);

    expect(screen.getByRole('note')).toHaveTextContent('check each item’s provenance badge');
  });

  it('is absent for observed data only', () => {
    render(<DemoBanner kinds={['observed']} />);

    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });

  it('is absent when no data is stored', () => {
    render(<DemoBanner kinds={[]} />);

    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});
