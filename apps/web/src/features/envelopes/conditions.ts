import type { FormField } from "./api";

type Conditioned = Pick<FormField, "id" | "depends_on">;

/**
 * The fields that are asked, given these values (the server's envelopes.sending.asked). A field
 * under a condition is asked only when the field it depends on is itself asked and holds that
 * option (a checkbox: ticked), so a value left in a field that is no longer shown never keeps what
 * depends on it. Each chain is walked once, whatever order the fields come in: O(F).
 */
export function askedFields(fields: readonly Conditioned[], values: Readonly<Record<string, string>>): Set<string> {
  const byId = new Map(fields.map((field) => [field.id, field]));
  const known = new Map<string, boolean>();
  for (const start of fields) {
    const path: { id: string; condition: NonNullable<Conditioned["depends_on"]> }[] = [];
    let node: Conditioned | undefined = start;
    while (node && !known.has(node.id)) {
      if (!node.depends_on) {
        known.set(node.id, true);
        break;
      }
      known.set(node.id, false); // until its chain is walked; a chain that loops is not asked
      path.push({ id: node.id, condition: node.depends_on });
      node = byId.get(node.depends_on.field_id);
    }
    let met = node !== undefined && known.get(node.id) === true;
    for (const { id, condition } of path.reverse()) {
      const given = values[condition.field_id];
      met = met && (given === condition.option || (condition.option === "checked" && given === "true"));
      known.set(id, met);
    }
  }
  return new Set([...known].filter(([, isAsked]) => isAsked).map(([id]) => id));
}
