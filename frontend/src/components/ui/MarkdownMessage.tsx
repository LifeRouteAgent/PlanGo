import type { ReactNode } from "react";

interface MarkdownMessageProps {
  content: string;
}

type Block =
  | { type: "heading"; level: 3 | 4; text: string }
  | { type: "paragraph"; text: string }
  | { type: "ul"; items: string[] }
  | { type: "ol"; items: string[] };

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  const blocks = parseMarkdownBlocks(content);
  return (
    <div className="markdown-message">
      {blocks.map((block, index) => renderBlock(block, index))}
    </div>
  );
}

function parseMarkdownBlocks(content: string): Block[] {
  const normalized = content
    .replace(/\r\n/g, "\n")
    .replace(/\s+(#{3,4})\s+/g, "\n$1 ")
    .replace(/\s+(\d+[.)])\s+/g, "\n$1 ")
    .replace(/\s+([*\u2022-])\s+/g, "\n$1 ");
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

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushParagraph();
      flushLists();
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
