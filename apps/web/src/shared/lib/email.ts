/** The message the server also uses for a malformed address (identity domain ``normalize_email``). */
export const INVALID_EMAIL = "Enter a valid email address";

/**
 * Whether ``value`` is shaped like an email address, for instant feedback. It applies the browser's
 * own rule (the HTML standard's definition behind ``<input type="email">``), plus a dot in the
 * domain as the server requires. The server's check stays the authority on save.
 */
export function looksLikeEmail(value: string): boolean {
  const candidate = value.trim();
  if (!candidate || typeof document === "undefined") return false;
  const input = document.createElement("input");
  input.type = "email";
  input.value = candidate;
  if (!input.checkValidity()) return false;
  const domain = candidate.slice(candidate.lastIndexOf("@") + 1);
  return /^[^.]+(\.[^.]+)+$/.test(domain);
}
