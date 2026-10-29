/// <reference types="node" />
// Node types are scoped to this file: it reads the stylesheet's source, which the bundler would
// otherwise compile (Tailwind removes the `@theme` block).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const css = readFileSync(resolve(import.meta.dirname, '../index.css'), 'utf-8');

type Tokens = Record<string, string>;

/** The `--color-*: #hex;` declarations inside the block that starts at `opening`. */
function tokensIn(opening: string): Tokens {
  const start = css.indexOf(opening);
  if (start < 0) throw new Error(`Block not found in index.css: ${opening}`);
  const open = css.indexOf('{', start);
  let depth = 0;
  let end = open;
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++;
    if (css[i] === '}') depth--;
    if (depth === 0) {
      end = i;
      break;
    }
  }
  const body = css.slice(open + 1, end);
  const tokens: Tokens = {};
  for (const match of body.matchAll(/--color-([a-z-]+):\s*(#[0-9a-fA-F]{6})/g)) {
    const [, name, value] = match;
    if (name !== undefined && value !== undefined) tokens[name] = value.toLowerCase();
  }
  return tokens;
}

const light = tokensIn('@theme');
const darkChosen = tokensIn(":root[data-theme='dark']");
const darkSystem = tokensIn(':root:not([data-theme])');
const dark: Tokens = { ...light, ...darkChosen };

function luminance(hex: string): number {
  const channel = (offset: number) => {
    const value = parseInt(hex.slice(offset, offset + 2), 16) / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

/** Text token on background token, as the components pair them. */
const PAIRS: readonly [text: string, background: string][] = [
  ['ink', 'surface'],
  ['ink', 'raised'],
  ['ink', 'sunken'],
  ['ink', 'danger-soft'],
  ['muted', 'surface'],
  ['muted', 'raised'],
  ['muted', 'sunken'],
  ['accent-ink', 'accent'],
  ['success', 'raised'],
  ['danger', 'danger-soft'],
  ['raised', 'danger'],
  ['synthetic', 'synthetic-soft'],
  ['observed', 'observed-soft'],
  ['uploaded', 'uploaded-soft'],
];

describe('design tokens', () => {
  it('defines the same tokens in every theme', () => {
    expect(Object.keys(darkChosen).sort()).toEqual(Object.keys(darkSystem).sort());
    for (const name of Object.keys(darkChosen)) expect(light[name]).toBeDefined();
  });

  it('keeps the system dark theme identical to the chosen dark theme', () => {
    expect(darkSystem).toEqual(darkChosen);
  });

  it.each(PAIRS)('%s on %s has WCAG AA contrast (4.5:1) in the light theme', (text, background) => {
    const foreground = light[text];
    const surface = light[background];
    expect(foreground).toBeDefined();
    expect(surface).toBeDefined();
    expect(contrast(foreground ?? '', surface ?? '')).toBeGreaterThanOrEqual(4.5);
  });

  it.each(PAIRS)('%s on %s has WCAG AA contrast (4.5:1) in the dark theme', (text, background) => {
    const foreground = dark[text];
    const surface = dark[background];
    expect(foreground).toBeDefined();
    expect(surface).toBeDefined();
    expect(contrast(foreground ?? '', surface ?? '')).toBeGreaterThanOrEqual(4.5);
  });

  it.each([
    ['edge', 'raised'],
    ['edge', 'surface'],
  ])(
    'the %s of a control on %s has 3:1 contrast (WCAG 1.4.11) in both themes',
    (edge, background) => {
      for (const theme of [light, dark]) {
        expect(contrast(theme[edge] ?? '', theme[background] ?? '')).toBeGreaterThanOrEqual(3);
      }
    },
  );

  it('measures contrast correctly (black on white is 21:1)', () => {
    expect(contrast('#000000', '#ffffff')).toBeCloseTo(21, 5);
  });
});
