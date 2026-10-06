import { lazy, Suspense, type ReactNode } from "react";

const MathFormula = lazy(() => import("./MathFormula"));

// Lightweight, dependency-free Markdown renderer. Supports the subset that the
// analysis / QA pipeline emits: headings, bold, italic, inline code, links,
// blockquotes, ordered/unordered lists and horizontal rules. Kept local so the
// app keeps rendering with no network access (no remote markdown package).

const INLINE_PATTERN =
  /(\*\*([^*]+)\*\*)|(`([^`]+)`)|(\*([^*]+)\*)|(_([^_]+)_)|(\[([^\]]+)\]\(([^)\s]+)\))/g;

function renderTextInline(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let token = 0;
  let match: RegExpExecArray | null;
  INLINE_PATTERN.lastIndex = 0;
  while ((match = INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(text.slice(lastIndex, match.index));
    }
    const key = `${keyPrefix}-${token++}`;
    if (match[2] !== undefined) {
      nodes.push(<strong key={key}>{match[2]}</strong>);
    } else if (match[4] !== undefined) {
      nodes.push(<code key={key}>{match[4]}</code>);
    } else if (match[6] !== undefined) {
      nodes.push(<em key={key}>{match[6]}</em>);
    } else if (match[8] !== undefined) {
      nodes.push(<em key={key}>{match[8]}</em>);
    } else if (match[10] !== undefined) {
      nodes.push(
        <a key={key} href={match[11]} target="_blank" rel="noreferrer">
          {match[10]}
        </a>
      );
    }
    lastIndex = INLINE_PATTERN.lastIndex;
  }
  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  // Protect math from Markdown emphasis (notably underscores and asterisks).
  const pattern = /(`[^`]+`)|(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$[^\n$]+?\$)/g;
  const nodes: ReactNode[] = [];
  let offset = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index!;
    nodes.push(...renderTextInline(text.slice(offset, start), `${keyPrefix}-${offset}`));
    const raw = match[0];
    if (match[1]) nodes.push(...renderTextInline(raw, `${keyPrefix}-code-${start}`));
    else {
      const display = raw.startsWith("$$") || raw.startsWith("\\[");
      const delimiter = raw.startsWith("$") && !display ? 1 : 2;
      nodes.push(<Suspense key={`${keyPrefix}-math-${start}`} fallback={<code>{raw}</code>}>
        <MathFormula source={raw.slice(delimiter, -delimiter)} display={display} />
      </Suspense>);
    }
    offset = start + raw.length;
  }
  nodes.push(...renderTextInline(text.slice(offset), `${keyPrefix}-${offset}`));
  return nodes;
}

export default function Markdown({
  content,
  className,
}: {
  content: string;
  className?: string;
}) {
  const lines = content.replace(/\r\n/g, "\n").split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let key = 0;
  let index = 0;

  const flushParagraph = () => {
    if (paragraph.length === 0) {
      return;
    }
    const text = paragraph.join(" ").trim();
    if (text) {
      blocks.push(<p key={`p${key}`}>{renderInline(text, `p${key}`)}</p>);
      key += 1;
    }
    paragraph = [];
  };

  while (index < lines.length) {
    const trimmed = lines[index].trim();

    if (!trimmed) {
      flushParagraph();
      index += 1;
      continue;
    }

    const fence = /^(`{3,}|~{3,})(.*)$/.exec(trimmed);
    if (fence) {
      flushParagraph();
      const code: string[] = [];
      index += 1;
      const closing = new RegExp(`^${fence[1][0]}{${fence[1].length},}\\s*$`);
      while (index < lines.length && !closing.test(lines[index].trim())) {
        code.push(lines[index++]);
      }
      if (index < lines.length) index += 1;
      blocks.push(<pre key={`code${key++}`}><code>{code.join("\n")}</code></pre>);
      continue;
    }

    if (trimmed.startsWith("$$") || trimmed.startsWith("\\[")) {
      flushParagraph();
      const closing = trimmed.startsWith("$$") ? "$$" : "\\]";
      let expression = trimmed;
      index += 1;
      while (expression.indexOf(closing, 2) < 0 && index < lines.length) expression += "\n" + lines[index++];
      blocks.push(<div key={`math${key++}`}>{renderInline(expression, `display-${key}`)}</div>);
      continue;
    }

    const cells = (line: string) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
    if (trimmed.includes("|") && index + 1 < lines.length &&
        cells(lines[index + 1]).every((cell) => /^:?-{3,}:?$/.test(cell))) {
      flushParagraph();
      const headers = cells(trimmed);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes("|")) {
        rows.push(cells(lines[index++]));
      }
      const tableKey = key++;
      blocks.push(<div className="markdown-table" key={`table${tableKey}`}><table>
        <thead><tr>{headers.map((cell, i) => <th key={i}>{renderInline(cell, `th${tableKey}-${i}`)}</th>)}</tr></thead>
        <tbody>{rows.map((row, r) => <tr key={r}>{headers.map((_, c) => <td key={c}>{renderInline(row[c] ?? "", `td${tableKey}-${r}-${c}`)}</td>)}</tr>)}</tbody>
      </table></div>);
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flushParagraph();
      const level = Math.min(heading[1].length + 1, 6);
      const Tag = `h${level}` as keyof JSX.IntrinsicElements;
      blocks.push(<Tag key={`h${key}`}>{renderInline(heading[2], `h${key}`)}</Tag>);
      key += 1;
      index += 1;
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushParagraph();
      blocks.push(<hr key={`hr${key}`} />);
      key += 1;
      index += 1;
      continue;
    }

    if (trimmed.startsWith(">")) {
      flushParagraph();
      const quote: string[] = [];
      while (index < lines.length && lines[index].trim().startsWith(">")) {
        quote.push(lines[index].trim().replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(
        <blockquote key={`bq${key}`}>{renderInline(quote.join(" "), `bq${key}`)}</blockquote>
      );
      key += 1;
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      flushParagraph();
      const items: string[] = [];
      while (index < lines.length && /^[-*+]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*+]\s+/, ""));
        index += 1;
      }
      const listKey = key;
      blocks.push(
        <ul key={`ul${listKey}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item, `ul${listKey}-${itemIndex}`)}</li>
          ))}
        </ul>
      );
      key += 1;
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      flushParagraph();
      const items: string[] = [];
      while (index < lines.length && /^\d+\.\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^\d+\.\s+/, ""));
        index += 1;
      }
      const listKey = key;
      blocks.push(
        <ol key={`ol${listKey}`}>
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item, `ol${listKey}-${itemIndex}`)}</li>
          ))}
        </ol>
      );
      key += 1;
      continue;
    }

    paragraph.push(trimmed);
    index += 1;
  }

  flushParagraph();

  return <div className={className ? `markdown-body ${className}` : "markdown-body"}>{blocks}</div>;
}
