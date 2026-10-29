import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import { KpiCard } from './KpiCard';

function card(estimate = false) {
  return (
    <KpiCard
      label="Potential excess energy"
      value="558.7"
      unit="MWh"
      note="Not verified savings."
      definition="Energy above the upper bound."
      source="Stored alerts."
      estimate={estimate}
    />
  );
}

describe('KpiCard', () => {
  it('shows the label, value, unit and note', () => {
    render(card());

    const region = screen.getByRole('region', { name: 'Potential excess energy' });
    expect(region).toHaveTextContent('558.7');
    expect(region).toHaveTextContent('MWh');
    expect(region).toHaveTextContent('Not verified savings.');
  });

  it('marks an estimate in words', () => {
    render(card(true));

    expect(screen.getByText('Estimate')).toBeInTheDocument();
  });

  it('has no estimate mark unless asked', () => {
    render(card());

    expect(screen.queryByText('Estimate')).not.toBeInTheDocument();
  });

  it('gives its definition and source to assistive technology at all times', () => {
    render(card());

    const button = screen.getByRole('button', { name: 'About Potential excess energy' });
    expect(button).toHaveAccessibleDescription(
      /Energy above the upper bound\..*Source: Stored alerts\./,
    );
  });

  it('opens on focus and closes on Escape', async () => {
    render(card());
    const button = screen.getByRole('button', { name: 'About Potential excess energy' });
    expect(button).toHaveAttribute('aria-expanded', 'false');

    await userEvent.tab();
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('tooltip')).toHaveClass('block');

    await userEvent.keyboard('{Escape}');
    expect(button).toHaveAttribute('aria-expanded', 'false');
    expect(screen.getByRole('tooltip', { hidden: true })).toHaveClass('hidden');
  });

  it('opens on hover and closes when the pointer leaves', async () => {
    render(card());
    const button = screen.getByRole('button', { name: 'About Potential excess energy' });

    await userEvent.hover(button);
    expect(button).toHaveAttribute('aria-expanded', 'true');

    await userEvent.unhover(button);
    expect(button).toHaveAttribute('aria-expanded', 'false');
  });

  it('closes when focus moves away', async () => {
    render(card());
    const button = screen.getByRole('button', { name: 'About Potential excess energy' });

    await userEvent.tab();
    await userEvent.tab();

    expect(button).toHaveAttribute('aria-expanded', 'false');
  });
});
