/**
 * A docs page's MDX source, prepared for the plain-text routes.
 *
 * `/docs/<slug>.md` and `/llms-full.txt` serve each collection entry's own
 * source. MDX comments (`{/* … *\/}`) in it are notes for maintainers — the
 * release tooling's `x-release-please-version` markers, design decisions
 * recorded beside the prose they explain — and the rendered page drops them.
 * Served raw, an agent reads text the HTML never showed, so both routes strip
 * them first.
 *
 * Fenced code is left alone: a comment written inside a fence is literal text
 * on the rendered page, and the text routes must say the same thing.
 */

// The comment body may not contain `*/}`, so a match ends at the first close.
const COMMENT = String.raw`\{\/\*(?:(?!\*\/\})[\s\S])*\*\/\}`;
// A comment on lines of its own goes with its line break; one beside prose
// takes the whitespace before it, so `3.4.1 {/* … */}` leaves `3.4.1`.
const OWN_LINES = new RegExp(String.raw`^[ \t]*${COMMENT}[ \t]*\n`, 'gm');
const BESIDE_PROSE = new RegExp(String.raw`[ \t]*${COMMENT}`, 'g');
const FENCE = /^[ \t]*(`{3,}|~{3,})/;

function stripProse(text: string): string {
  return text.replace(OWN_LINES, '').replace(BESIDE_PROSE, '');
}

export function stripMdxComments(source: string): string {
  const out: string[] = [];
  let prose: string[] = [];
  let fence: string | null = null;

  const flush = () => {
    if (prose.length > 0) out.push(stripProse(prose.join('\n')));
    prose = [];
  };

  for (const line of source.split('\n')) {
    if (fence === null) {
      const open = FENCE.exec(line);
      if (open) {
        flush();
        fence = open[1];
        out.push(line);
      } else {
        prose.push(line);
      }
      continue;
    }
    out.push(line);
    // A fence closes on a run of the same character at least as long as the
    // one that opened it, with nothing after it but whitespace.
    const close = FENCE.exec(line);
    if (
      close &&
      close[1][0] === fence[0] &&
      close[1].length >= fence.length &&
      line.trim() === close[1]
    ) {
      fence = null;
    }
  }
  flush();
  return out.join('\n');
}
