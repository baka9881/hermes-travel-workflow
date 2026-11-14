// Fixed messages the bot prints fit a phone line too (2026-11-14: the "no flights" notice was wider
// than a phone line, so the daily self-check reported it as "手機會折行" instead of the real problem).
import { test } from 'vitest';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { tooWide } from './format';

const source = readFileSync(new URL('./cli.ts', import.meta.url), 'utf8');

/** Plain string literals printed with console.log (template strings are checked by `deals check`). */
function printedLiterals(): { line: number; text: string }[] {
  const found: { line: number; text: string }[] = [];
  for (const match of source.matchAll(/console\.log\('((?:[^'\\]|\\.)*)'\)/g)) {
    const text = match[1]!.replace(/\\n/g, '\n').replace(/\\'/g, "'");
    found.push({ line: source.slice(0, match.index).split('\n').length, text });
  }
  return found;
}

test('fixed messages are found', () => {
  assert.ok(printedLiterals().some(({ text }) => text.includes('這次沒讀到航班')));
});

test('no fixed message wraps on a phone', () => {
  const wide = printedLiterals().flatMap(({ line, text }) => tooWide(text).map(shown => `cli.ts:${line} ${shown}`));
  assert.deepEqual(wide, []);
});
