// Portable compatibility boundary: scanner output stays local; Hermes owns delivery.
const MAX_TEXT = 4000; // Telegram's limit is 4096 characters per message
const CALLBACK_PREFIX = 'ff:';
const MAX_CALLBACK_BYTES = 64; // Telegram's limit for callback_data

/** "ff:B4 東京", falling back to just the code when a long label passes Telegram's byte limit. */
export function callbackData(label: string): string {
  const data = `${CALLBACK_PREFIX}${label}`;
  return Buffer.byteLength(data) <= MAX_CALLBACK_BYTES ? data : `${CALLBACK_PREFIX}${label.split(' ')[0]}`;
}

// Telegram counts the text a message shows, not the URLs behind its links (booking links run to 1,400 characters).
const shownLength = (text: string) => text.replace(/\]\([^)\s]*\)/g, ']').length;

// Telegram also caps the link URLs one message may carry (ENTITIES_TOO_LONG); twelve booking links overran it.
const MAX_LINK_CHARS = 5000;
const linkLength = (text: string) => [...text.matchAll(/\]\(([^)\s]*)\)/g)].reduce((sum, match) => sum + match[1]!.length, 0);

/**
 * Split into messages under Telegram's text and link limits, breaking only
 * between blocks (a hotel "1. …", an area "📍 …") so no hotel is cut in half.
 */
export function chunks(text: string): string[] {
  const blocks: string[] = [];
  for (const line of text.split('\n')) {
    if (!blocks.length || /^(\d+\. |📍)/.test(line)) blocks.push(line);
    else blocks[blocks.length - 1] += `\n${line}`;
  }
  const parts: string[] = [];
  let current = '';
  for (const block of blocks) {
    const joined = current ? `${current}\n${block}` : block;
    if (current && (shownLength(joined) > MAX_TEXT || linkLength(joined) > MAX_LINK_CHARS)) { parts.push(current); current = block; }
    else current = joined;
  }
  if (current) parts.push(current);
  return parts;
}

/** A stretch of the output; one with photos is sent as a photo album captioned by its own text. */
export interface Segment { text: string; photos: string[]; own?: boolean } // own: always its own message (a hotel)

/** Retain the upstream call signature while disabling all direct account access and sends. */
export async function sendToTelegram(segments: readonly Segment[], _keyboard: readonly (readonly string[])[]): Promise<void> {
  for (const segment of segments) {
    if (segment.text) process.stdout.write(`${segment.text}\n`);
  }
}
