/** Joins truthy class names: cx("a", cond && "b") -> "a b". */
export function cx(...names: Array<string | false | null | undefined>): string {
  return names.filter(Boolean).join(" ");
}
