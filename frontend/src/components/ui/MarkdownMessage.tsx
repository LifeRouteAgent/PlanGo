import type { ReactNode } from "react";

interface MarkdownMessageProps {
  content: string;
}

type Block =
  | { type: "heading"; level: 3 | 4; text: string }
  | { type: "paragraph"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] }
  | { type: "table"; headers: string[]; rows: string[][] };

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  const blocks = parseMarkdownBlocks(content);
  return (
    <div className="markdown-message">
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  );
}

function parseMarkdownBlocks(content: string): Block[] {
  const normalized = expandCompactTables(
    content
      .replace(/\r\n/g, "\n")
      .replace(/\s+(#{3,4})\s+/g, "\n$1 ")
      .replace(/\s+(\d+[.)])\s+/g, "\n$1 ")
      .replace(/\s+([*\u2022-])\s+/g, "\n$1 ")
  );
  const lines = normalized.split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let unordered: string[] = [];
  let ordered: string[] = [];

  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", text: paragraph.join(" ").trim() });
      paragraph = [];
    }
  };
  const flushLists = () => {
    if (unordered.length) {
      blocks.push({ type: "ul", items: unordered });
      unordered = [];
    }
    if (ordered.length) {
      blocks.push({ type: "ol", items: ordered });
      ordered = [];
    }
  };

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index].trim();
    if (!line) {
      flushParagraph();
      flushLists();
      continue;
    }

    if (isTableLine(line)) {
      flushParagraph();
      flushLists();
      const tableLines = [line];
      while (index + 1 < lines.length && isTableLine(lines[index + 1].trim())) {
        index += 1;
        tableLines.push(lines[index].trim());
      }
      const table = parseTable(tableLines);
      if (table) {
        blocks.push(table);
      } else {
        paragraph.push(tableLines.join(" "));
      }
      continue;
    }

    const heading = line.match(/^(#{3,4})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      flushLists();
      blocks.push({ type: "heading", level: heading[1].length as 3 | 4, text: heading[2] });
      continue;
    }

    const orderedItem = line.match(/^\d+[.)]\s+(.+)$/);
    if (orderedItem) {
      flushParagraph();
      unordered = [];
      ordered.push(orderedItem[1]);
      continue;
    }

    const unorderedItem = line.match(/^[-*\u2022]\s+(.+)$/);
    if (unorderedItem) {
      flushParagraph();
      ordered = [];
      unordered.push(unorderedItem[1]);
      continue;
    }

    flushLists();
    paragraph.push(line);
  }

  flushParagraph();
  flushLists();
  return blocks;
}

function expandCompactTables(content: string): string {
  return content
    .split("\n")
    .map((line) => expandCompactTableLine(line))
    .join("\n");
}

function expandCompactTableLine(line: string): string {
  if (!line.includes("|") || !line.includes("---")) {
    return line;
  }

  const cells = line
    .split("|")
    .map((cell) => cell.trim())
    .filter(Boolean);
  const firstDividerIndex = cells.findIndex(isDividerCell);
  if (firstDividerIndex <= 0) {
    return line;
  }

  const columnCount = firstDividerIndex;
  const dividerCells = cells.slice(firstDividerIndex, firstDividerIndex + columnCount);
  if (dividerCells.length !== columnCount || !dividerCells.every(isDividerCell)) {
    return line;
  }

  const rows: string[][] = [];
  for (let index = 0; index < cells.length; index += columnCount) {
    const row = cells.slice(index, index + columnCount);
    if (row.length === columnCount) {
      rows.push(row);
    }
  }

  if (rows.length < 2) {
    return line;
  }
  return rows.map((row) => `| ${row.join(" | ")} |`).join("\n");
}

function isDividerCell(cell: string): boolean {
  return /^:?-{3,}:?$/.test(cell.trim());
}

function isTableLine(line: string): boolean {
  return line.startsWith("|") && line.endsWith("|") && line.split("|").length >= 4;
}

function parseTable(lines: string[]): Block | null {
  const rows = lines.map((line) =>
    line
      .split("|")
      .map((cell) => cell.trim())
      .filter(Boolean)
  );
  if (rows.length < 2) {
    return null;
  }
  const dividerIndex = rows.findIndex((row) => row.length > 0 && row.every(isDividerCell));
  if (dividerIndex <= 0) {
    return null;
  }
  const headers = rows[0];
  const bodyRows = rows.slice(dividerIndex + 1).filter((row) => row.length === headers.length);
  if (!headers.length || !bodyRows.length) {
    return null;
  }
  return { type: "table", headers, rows: bodyRows };
}

function renderBlock(block: Block, index: number) {
  if (block.type === "heading") {
    const Tag = block.level === 3 ? "h3" : "h4";
    return <Tag key={index}>{renderInline(block.text)}</Tag>;
  }
  if (block.type === "ul") {
    return (
      <ul key={index}>
        {block.items.map((item, itemIndex) => (
          <li key={`${index}-${itemIndex}`}>{renderInline(item)}</li>
        ))}
      </ul>
    );
  }
  if (block.type === "ol") {
    return (
      <ol key={index}>
        {block.items.map((item, itemIndex) => (
          <li key={`${index}-${itemIndex}`}>{renderInline(item)}</li>
        ))}
      </ol>
    );
  }
  if (block.type === "table") {
    return (
      <div className="markdown-table-wrap" key={index}>
        <table>
          <thead>
            <tr>
              {block.headers.map((header) => (
                <th key={header}>{renderInline(header)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row, rowIndex) => (
              <tr key={`${index}-${rowIndex}`}>
                {row.map((cell, cellIndex) => (
                  <td key={`${index}-${rowIndex}-${cellIndex}`}>{renderInline(cell)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  return <p key={index}>{renderInline(block.text)}</p>;
}

function renderInline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean).map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}
