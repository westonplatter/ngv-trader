import type { ReactNode } from "react";

// Matches http:// and https:// URLs. Trailing punctuation that is more likely
// sentence punctuation than part of the URL is trimmed off the match below.
const URL_PATTERN = /(https?:\/\/[^\s<]+)/g;

// Punctuation that commonly follows a URL in prose but isn't part of it.
const TRAILING_PUNCTUATION = /[.,;:!?)\]}'"]+$/;

/**
 * Turn plain text into React nodes with any http(s) URLs rendered as
 * clickable links. Non-URL text is returned verbatim, so the caller keeps
 * control of surrounding styling (e.g. whitespace-pre-wrap).
 *
 * Links open in a new tab with rel="noopener noreferrer" for safety.
 */
export function linkify(text: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;

  for (const match of text.matchAll(URL_PATTERN)) {
    const raw = match[0];
    const start = match.index ?? 0;

    // Push the plain text preceding this URL.
    if (start > lastIndex) {
      nodes.push(text.slice(lastIndex, start));
    }

    // Trim trailing punctuation off the URL and render it as plain text so a
    // sentence like "see https://example.com." doesn't swallow the period.
    const trailing = TRAILING_PUNCTUATION.exec(raw)?.[0] ?? "";
    const url = trailing ? raw.slice(0, raw.length - trailing.length) : raw;

    nodes.push(
      <a
        key={`link-${key++}`}
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="text-blue-600 underline hover:text-blue-800"
      >
        {url}
      </a>,
    );
    if (trailing) nodes.push(trailing);

    lastIndex = start + raw.length;
  }

  // Push any remaining trailing text.
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }

  return nodes;
}
