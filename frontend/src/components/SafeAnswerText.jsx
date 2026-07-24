import { Fragment } from "react";

function isOpeningBoundary(character) {
  return character == null || /[\s([{'"“‘:;,!?—–-]/u.test(character);
}

function isClosingBoundary(character) {
  return character == null || /[\s)\]}'"”’.,:;!?—–-]/u.test(character);
}

function findClosingMarker(text, marker, fromIndex) {
  let cursor = fromIndex;
  while (cursor < text.length) {
    const index = text.indexOf(marker, cursor);
    if (index < 0) return -1;
    const previous = text[index - 1];
    const following = text[index + marker.length];
    if (
      previous
      && !/\s/u.test(previous)
      && isClosingBoundary(following)
      && text[index - 1] !== "\\"
    ) {
      return index;
    }
    cursor = index + marker.length;
  }
  return -1;
}

export function renderSafeInline(text, keyPrefix = "inline") {
  const source = String(text ?? "");
  const output = [];
  let buffer = "";
  let cursor = 0;

  const flush = () => {
    if (!buffer) return;
    output.push(buffer);
    buffer = "";
  };

  while (cursor < source.length) {
    if (source[cursor] === "\\" && source[cursor + 1] === "*") {
      buffer += "*";
      cursor += 2;
      continue;
    }

    if (source[cursor] === "`") {
      const closing = source.indexOf("`", cursor + 1);
      if (closing > cursor + 1) {
        flush();
        output.push(
          <code
            key={`${keyPrefix}-code-${cursor}`}
            className="rounded bg-black/30 px-1 py-0.5 font-mono text-[0.92em] text-white/85"
          >
            {source.slice(cursor + 1, closing)}
          </code>,
        );
        cursor = closing + 1;
        continue;
      }
    }

    if (
      source.startsWith("**", cursor)
      && isOpeningBoundary(source[cursor - 1])
      && source[cursor + 2]
      && !/\s/u.test(source[cursor + 2])
    ) {
      const closing = findClosingMarker(source, "**", cursor + 2);
      if (closing > cursor + 2) {
        flush();
        output.push(
          <strong key={`${keyPrefix}-strong-${cursor}`} className="font-semibold text-white/95">
            {renderSafeInline(source.slice(cursor + 2, closing), `${keyPrefix}-strong-${cursor}`)}
          </strong>,
        );
        cursor = closing + 2;
        continue;
      }
    }

    if (
      source[cursor] === "*"
      && source[cursor + 1] !== "*"
      && isOpeningBoundary(source[cursor - 1])
      && source[cursor + 1]
      && !/\s/u.test(source[cursor + 1])
    ) {
      const closing = findClosingMarker(source, "*", cursor + 1);
      if (closing > cursor + 1) {
        flush();
        output.push(
          <em key={`${keyPrefix}-em-${cursor}`} className="italic">
            {renderSafeInline(source.slice(cursor + 1, closing), `${keyPrefix}-em-${cursor}`)}
          </em>,
        );
        cursor = closing + 1;
        continue;
      }
    }

    buffer += source[cursor];
    cursor += 1;
  }

  flush();
  return output;
}

function parseBlocks(text) {
  const lines = String(text ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let paragraph = [];
  let list = null;
  let code = null;

  const flushParagraph = () => {
    if (!paragraph.length) return;
    blocks.push({ type: "paragraph", lines: paragraph });
    paragraph = [];
  };
  const flushList = () => {
    if (!list) return;
    blocks.push(list);
    list = null;
  };
  const flushCode = () => {
    if (!code) return;
    blocks.push(code);
    code = null;
  };

  lines.forEach((line) => {
    const fence = line.match(/^\s*```([^`]*)$/u);
    if (fence) {
      flushParagraph();
      flushList();
      if (code) flushCode();
      else code = { type: "code", language: fence[1].trim(), lines: [] };
      return;
    }

    if (code) {
      code.lines.push(line);
      return;
    }

    const bullet = line.match(/^\s*[-*•]\s+(.+)$/u);
    const numbered = line.match(/^\s*\d+[.)]\s+(.+)$/u);
    if (bullet || numbered) {
      flushParagraph();
      const type = numbered ? "ordered-list" : "unordered-list";
      if (list && list.type !== type) flushList();
      if (!list) list = { type, items: [] };
      list.items.push((bullet || numbered)[1]);
      return;
    }

    if (!line.trim()) {
      flushParagraph();
      flushList();
      return;
    }

    flushList();
    paragraph.push(line);
  });

  flushParagraph();
  flushList();
  flushCode();
  return blocks;
}

export function SafeAnswerText({ text, className = "", testId }) {
  const blocks = parseBlocks(text);
  return (
    <div
      className={`safe-answer-content min-w-0 max-w-full break-words [overflow-wrap:anywhere] ${className}`.trim()}
      data-testid={testId}
    >
      {blocks.map((block, index) => {
        if (block.type === "code") {
          return (
            <pre
              key={`code-${index}`}
              className="my-3 max-w-full overflow-x-auto rounded-xl border border-white/10 bg-black/30 p-3 text-[12.5px] leading-relaxed"
            >
              <code>{block.lines.join("\n")}</code>
            </pre>
          );
        }

        if (block.type === "unordered-list" || block.type === "ordered-list") {
          const List = block.type === "ordered-list" ? "ol" : "ul";
          return (
            <List
              key={`list-${index}`}
              className={`my-3 space-y-1.5 pl-5 ${block.type === "ordered-list" ? "list-decimal" : "list-disc"}`}
            >
              {block.items.map((item, itemIndex) => (
                <li key={`item-${itemIndex}`} className="pl-1">
                  {renderSafeInline(item, `list-${index}-${itemIndex}`)}
                </li>
              ))}
            </List>
          );
        }

        return (
          <p key={`paragraph-${index}`} className="my-3 first:mt-0 last:mb-0 whitespace-pre-wrap">
            {block.lines.map((line, lineIndex) => (
              <Fragment key={`line-${lineIndex}`}>
                {lineIndex > 0 && <br />}
                {renderSafeInline(line, `paragraph-${index}-${lineIndex}`)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </div>
  );
}
