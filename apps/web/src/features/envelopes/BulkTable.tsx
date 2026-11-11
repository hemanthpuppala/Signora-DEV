"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { cx } from "@/shared/lib/cx";
import { Checkbox, TextButton } from "@/shared/ui";

import styles from "./bulk.module.css";
import { hasError, type SheetColumn, type SheetProblem, type SheetRow } from "./bulkApi";

/** How many rows are added to the page at a time as the person scrolls (NFR-2). */
const PAGE = 50;

const INPUT_TYPE: Partial<Record<SheetColumn["kind"], string>> = { date: "date", email: "email" };

/** A choice's cell as the option it names: its value, given as the value or as its words. */
function chosen(column: SheetColumn, text: string): string {
  const plain = text.trim().toLowerCase();
  const option = (column.options ?? []).find(
    (o) => o.value.toLowerCase() === plain || o.text.trim().toLowerCase() === plain,
  );
  return option ? option.value : text;
}

const TICKED = new Set(["yes", "true", "x", "1", "y"]);

function Cell({
  column,
  row,
  problem,
  disabled,
  onChange,
  onLeave,
}: {
  column: SheetColumn;
  row: SheetRow;
  problem: SheetProblem | undefined;
  disabled: boolean;
  onChange: (value: string) => void;
  onLeave: () => void;
}) {
  const value = row.cells[column.key] ?? "";
  const id = `bulk-${row.row_no}-${column.key}`;
  const messageId = problem ? `${id}-problem` : undefined;
  const error = problem !== undefined && problem.level !== "warning";
  const shared = {
    id,
    disabled,
    "aria-label": `${column.header}, row ${row.row_no}`,
    "aria-invalid": error || undefined,
    "aria-describedby": messageId,
    "data-problem": error ? "" : undefined,
    onBlur: onLeave,
  };
  const className = cx(styles.input, problem?.level === "warning" && styles.warned);
  return (
    <div className={styles.cell}>
      {column.kind === "checkbox" ? (
        <span className={styles.tick}>
          <Checkbox
            {...shared}
            checked={TICKED.has(value.trim().toLowerCase())}
            onChange={(event) => {
              onChange(event.target.checked ? "yes" : "");
              onLeave();
            }}
          >
            {""}
          </Checkbox>
        </span>
      ) : column.kind === "choice" ? (
        <select
          {...shared}
          className={className}
          value={chosen(column, value)}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        >
          <option value="">—</option>
          {/* What the file gave, when it is none of the options, so it is seen and replaced. */}
          {value && !(column.options ?? []).some((o) => o.value === chosen(column, value)) ? (
            <option value={value}>{value}</option>
          ) : null}
          {(column.options ?? []).map((option) => (
            <option key={option.value} value={option.value}>
              {option.text}
            </option>
          ))}
        </select>
      ) : (
        <input
          {...shared}
          className={className}
          type={/^\d{4}-\d{2}-\d{2}$/.test(value) || !value ? (INPUT_TYPE[column.kind] ?? "text") : "text"}
          inputMode={column.kind === "number" ? "decimal" : undefined}
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      )}
      {problem ? (
        <span id={messageId} className={styles.message} data-level={problem.level ?? "error"}>
          {problem.message}
        </span>
      ) : null}
    </div>
  );
}

/**
 * A bulk send's rows as a table to correct in place (Bulk send §9): one row per envelope, a column
 * per thing the template asks. A cell with a problem is marked and says what is wrong under it;
 * correcting it and leaving the cell has the row checked again. The row's number and "Leave out"
 * stay in place while the table scrolls sideways, the header while it scrolls down. Rows are
 * added to the page as the person scrolls.
 */
export function BulkTable({
  columns,
  rows,
  leftOut,
  checking,
  onEdit,
  onLeaveCell,
  onLeaveOut,
}: {
  columns: readonly SheetColumn[];
  rows: readonly SheetRow[];
  /** The numbers of the rows that will not be sent. */
  leftOut: ReadonlySet<number>;
  checking: boolean;
  onEdit: (rowNo: number, key: string, value: string) => void;
  /** A cell was left after an edit: time to check the rows again. */
  onLeaveCell: () => void;
  onLeaveOut: (rowNo: number, out: boolean) => void;
}) {
  const [onlyProblems, setOnlyProblems] = useState(true);
  const [shown, setShown] = useState(PAGE);
  const scroller = useRef<HTMLDivElement>(null);
  const sentinel = useRef<HTMLTableRowElement>(null);

  const included = useMemo(() => rows.filter((row) => !leftOut.has(row.row_no)), [rows, leftOut]);
  const withErrors = useMemo(() => included.filter(hasError), [included]);
  const withWarnings = useMemo(
    () => included.filter((row) => !hasError(row) && (row.problems ?? []).length > 0),
    [included],
  );
  // The rows to work through stay listed while they are worked on: a row that has just been
  // corrected does not jump out from under the person; it leaves when the list is next opened.
  const [listed, setListed] = useState<ReadonlySet<number>>(
    () => new Set(rows.filter((row) => (row.problems ?? []).length > 0).map((row) => row.row_no)),
  );
  const visible = onlyProblems ? rows.filter((row) => listed.has(row.row_no)) : rows;
  const page = visible.slice(0, shown);

  useEffect(() => {
    const target = sentinel.current;
    if (!target || typeof IntersectionObserver === "undefined") return undefined;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) setShown((count) => count + PAGE);
      },
      { root: scroller.current, rootMargin: "200px" },
    );
    observer.observe(target);
    return () => observer.disconnect();
  }, [visible.length, shown]);

  const nextProblem = () => {
    const cells = Array.from(scroller.current?.querySelectorAll<HTMLElement>("[data-problem]") ?? []);
    if (cells.length === 0) return;
    const at = cells.indexOf(document.activeElement as HTMLElement);
    (cells[(at + 1) % cells.length] ?? cells[0])?.focus();
  };

  return (
    <div className={styles.stack}>
      <div className={styles.toolbar}>
        <span className={styles.count} role="status">
          {withErrors.length === 0
            ? `All ${included.length} ${included.length === 1 ? "row is" : "rows are"} ready to send`
            : `${withErrors.length} of ${included.length} ${included.length === 1 ? "row" : "rows"} ${withErrors.length === 1 ? "needs" : "need"} fixing`}
          {withWarnings.length > 0
            ? ` · ${withWarnings.length} to look at`
            : ""}
          {leftOut.size > 0 ? ` · ${leftOut.size} left out` : ""}
          {checking ? " · checking…" : ""}
        </span>
        <span className={styles.tools}>
          <Checkbox
            checked={onlyProblems}
            onChange={(event) => {
              setOnlyProblems(event.target.checked);
              setShown(PAGE);
              setListed(new Set(rows.filter((row) => (row.problems ?? []).length > 0).map((row) => row.row_no)));
            }}
          >
            Only rows with problems
          </Checkbox>
          <TextButton onClick={nextProblem} disabled={withErrors.length === 0}>
            Next problem
          </TextButton>
        </span>
      </div>
      <div className={styles.scroller} ref={scroller} tabIndex={-1}>
        <table className={styles.table} aria-label="Rows of the spreadsheet">
          <thead>
            <tr>
              <th scope="col" className={styles.rowHead}>
                Row
              </th>
              {columns.map((column) => (
                <th key={column.key} scope="col" className={cx(column.required && styles.required)}>
                  {column.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.map((row) => {
              const out = leftOut.has(row.row_no);
              const problems = new Map((row.problems ?? []).map((problem) => [problem.key, problem]));
              return (
                <tr key={row.row_no} className={cx(out && styles.out)}>
                  <th scope="row" className={styles.rowHead}>
                    <span className={styles.rowNo}>{`Row ${row.row_no}`}</span>
                    <button
                      type="button"
                      className={styles.rowAction}
                      aria-label={out ? `Put row ${row.row_no} back` : `Leave out row ${row.row_no}`}
                      onClick={() => onLeaveOut(row.row_no, !out)}
                    >
                      {out ? "Put back" : "Leave out"}
                    </button>
                  </th>
                  {columns.map((column) => (
                    <td key={column.key}>
                      <Cell
                        column={column}
                        row={row}
                        problem={out ? undefined : problems.get(column.key)}
                        disabled={out}
                        onChange={(value) => onEdit(row.row_no, column.key, value)}
                        onLeave={onLeaveCell}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
            {page.length < visible.length ? (
              <tr ref={sentinel}>
                <td colSpan={columns.length + 1} className={styles.more}>
                  {`Showing ${page.length} of ${visible.length} rows`}
                </td>
              </tr>
            ) : null}
            {visible.length === 0 ? (
              <tr>
                <td colSpan={columns.length + 1} className={styles.more}>
                  No rows with problems.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
