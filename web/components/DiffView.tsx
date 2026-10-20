import type { HunkView } from "@/lib/types";

interface Row { kind: "ctx" | "add" | "del"; oldNo: number | null; newNo: number | null; text: string }

export function hunkRows(hunk: Pick<HunkView, "old_start" | "new_start" | "text">): Row[] {
  let oldNo = hunk.old_start;
  let newNo = hunk.new_start;
  return hunk.text.split("\n").filter((l) => l.length > 0).map((line) => {
    const sign = line[0];
    const text = line.slice(1);
    if (sign === "+") return { kind: "add", oldNo: null, newNo: newNo++, text } as Row;
    if (sign === "-") return { kind: "del", oldNo: oldNo++, newNo: null, text } as Row;
    return { kind: "ctx", oldNo: oldNo++, newNo: newNo++, text } as Row;
  });
}

export function DiffHunk({ hunk, flaggedLines = [] }: { hunk: HunkView; flaggedLines?: number[] }) {
  const rows = hunkRows(hunk);
  return (
    <div className={`hunk ${hunk.label} diff`}>
      {rows.map((row, i) => (
        <div
          key={i}
          className={`diff-line ${row.kind}${row.newNo !== null && flaggedLines.includes(row.newNo) ? " flagged" : ""}`}
          data-line={row.newNo ?? undefined}
        >
          <span className="no">{row.oldNo ?? ""}</span>
          <span className="no">{row.newNo ?? ""}</span>
          <span className="sign">{row.kind === "add" ? "+" : row.kind === "del" ? "−" : " "}</span>
          <Code text={row.text} />
        </div>
      ))}
    </div>
  );
}

/** Leading indentation stays unmarked so the highlighter covers only the code itself. */
export function Code({ text }: { text: string }) {
  const indent = text.match(/^\s*/)?.[0] ?? "";
  const body = text.slice(indent.length);
  return <span className="code">{indent}{body ? <span className="txt">{body}</span> : " "}</span>;
}
