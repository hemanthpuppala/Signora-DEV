import type { ReactNode } from "react";

/** The interface's icons: line drawings in the text colour, one home for each shape. */
const SHAPES = {
  download: (
    <>
      <path d="M12 4v11" />
      <path d="m7 10.5 5 5 5-5" />
      <path d="M5 19.5h14" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  minus: <path d="M5 12h14" />,
  // Arrows: move something that way.
  up: <path d="M12 19V5M6.5 10.5 12 5l5.5 5.5" />,
  down: <path d="M12 5v14M6.5 13.5 12 19l5.5-5.5" />,
  left: <path d="M19 12H5M10.5 6.5 5 12l5.5 5.5" />,
  right: <path d="M5 12h14M13.5 6.5 19 12l-5.5 5.5" />,
  chevron: <path d="m9 6 6 6-6 6" />, // points right; turned to point down when open
  close: <path d="M6 6l12 12M18 6 6 18" />,
  // A bell: remind the people who still have to sign.
  bell: (
    <>
      <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 1.5h-15Z" />
      <path d="M10 20.5a2 2 0 0 0 4 0" />
    </>
  ),
  // A circle struck through: cancel (withdraw) something sent.
  cancel: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="m6 6 12 12" />
    </>
  ),
  // A tick: approve, done.
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  // A tick in a box: save.
  save: (
    <>
      <path d="M4.5 4.5h12l3 3v12h-15Z" />
      <path d="m8.5 12.5 2.5 2.5 4.5-5" />
    </>
  ),
  // An arrow turning back: undo the last change.
  undo: (
    <>
      <path d="M9 7.5 4.5 12 9 16.5" />
      <path d="M4.5 12h10a5 5 0 0 1 0 10h-2" />
    </>
  ),
  // A circle turning back: discard every unsaved change.
  discard: (
    <>
      <path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3" />
      <path d="M4 4.5v3.5h3.5" />
    </>
  ),
  // A paper plane: send for signature.
  send: (
    <>
      <path d="M20.5 3.5 3.5 10.5l7 3 3 7Z" />
      <path d="m10.5 13.5 10-10" />
    </>
  ),
  // Two sheets: something on every page.
  pages: (
    <>
      <path d="M8 3.5h8.5l3 3V17H8Z" />
      <path d="M5 7v13.5h11" />
    </>
  ),
  // One box becoming two: make a place its own field.
  split: (
    <>
      <path d="M4 5h7v6H4Z" />
      <path d="M13 13h7v6h-7Z" />
      <path d="m14 5 5 0M19 5v5" />
    </>
  ),
  trash: (
    <>
      <path d="M4.5 6.5h15" />
      <path d="M9.5 6.5V4.5h5v2" />
      <path d="M6.5 6.5 7.5 19.5h9l1-13" />
    </>
  ),
  settings: (
    <>
      <path d="M4 7h9M17 7h3M4 17h3M11 17h9" />
      <circle cx="15" cy="7" r="2" />
      <circle cx="9" cy="17" r="2" />
    </>
  ),
  star: <path d="m12 3 2.7 5.6 6.1.8-4.5 4.2 1.1 6.1L12 16.8l-5.4 2.9 1.1-6.1-4.5-4.2 6.1-.8Z" />,
  upload: (
    <>
      <path d="M12 15.5V4.5" />
      <path d="m7 9 5-5 5 5" />
      <path d="M5 19.5h14" />
    </>
  ),
  edit: (
    <>
      <path d="M15.5 5.5 18.5 8.5" />
      <path d="M4.5 19.5 5.3 15.7 16 5a2.1 2.1 0 0 1 3 3L8.3 18.7Z" />
    </>
  ),
  archive: (
    <>
      <path d="M4 5h16v4H4Z" />
      <path d="M5.5 9v10h13V9" />
      <path d="M10 13h4" />
    </>
  ),
} satisfies Record<string, ReactNode>;

export type IconName = keyof typeof SHAPES;

/**
 * An icon, hidden from assistive technology: whatever it sits in carries the words. ``filled``
 * fills the shape (a star that is on).
 */
export function Icon({
  name,
  size = 16,
  filled = false,
  className,
}: {
  name: IconName;
  size?: number;
  filled?: boolean | undefined;
  className?: string | undefined;
}) {
  return (
    <svg
      className={className}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {SHAPES[name]}
    </svg>
  );
}
