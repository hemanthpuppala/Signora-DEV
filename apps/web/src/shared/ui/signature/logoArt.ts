// The logo's still parts, shared by the animation (logoSigning) and the email logo the build
// draws from them (scripts/email-logo.mjs): one definition of what the logo looks like.
export const VIEW = { x: 19.25, y: -43.15, w: 304, h: 250 };
export const VANE = ["#ffffff", "#e4e4e4", "#8e8e8e"] as const;

// The quill, drawn with its nib at (18, 88).
export const QUILL = {
  vane: "M30 72C26 52 42 28 82 12C76 32 62 52 38 68Z",
  cuts: "M31.4 52.4L33.9 50.5L39.4 58.2Z M42.4 36.2L44.6 34.3L48.6 41.6Z M63.4 46.6L61.6 48.6L57.4 46.6Z",
  rachis:
    "M36.3 66.2L38.9 62.8L41.5 59.5L44.1 56.2L46.8 52.9L49.4 49.7L52.1 46.4L54.9 43.2L57.7 39.9L60.5 36.6L63.4 33.3L66.3 29.9L69.3 26.5L72.4 23.0L75.5 19.4L78.7 15.7L82.0 12.0L81.9 11.9L78.5 15.6L75.3 19.2L72.1 22.7L68.9 26.1L65.9 29.5L63.0 32.9L60.1 36.2L57.2 39.5L54.4 42.8L51.7 46.0L49.0 49.3L46.3 52.5L43.6 55.8L41.0 59.1L38.3 62.4L35.6 65.7Z",
  shaft:
    "M18.1 88.1L20.0 86.2L21.8 84.4L23.5 82.6L25.2 80.8L26.8 79.0L28.3 77.2L29.8 75.4L31.2 73.6L32.6 71.9L33.9 70.2L35.2 68.5L36.5 66.9L35.4 66.1L34.2 67.7L32.8 69.3L31.5 71.0L30.0 72.7L28.6 74.4L27.1 76.1L25.6 77.9L24.0 79.8L22.5 81.7L21.0 83.7L19.4 85.7L17.8 87.9Z",
};
