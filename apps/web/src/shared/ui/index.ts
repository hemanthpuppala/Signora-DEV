/** Design-system components (single source of styling; backbone LLD §8.6). */
export { AppShell, TopBar, type AppShellProps, type NavItem } from "./AppShell";
export { AuthPanel, type AuthPanelProps } from "./AuthPanel";
export { Button, TextButton, type ButtonProps, type ButtonVariant } from "./Button";
export { Checkbox, Radio } from "./Choice";
export {
  MetricGrid,
  MetricTile,
  Notice,
  STATUSES,
  StatusPill,
  TablePanel,
  Tabs,
  type Status,
  type TabItem,
} from "./Display";
export { TextArea, TextField } from "./Field";
export { PasswordField, type PasswordFieldProps } from "./PasswordField";
export { Select, type SelectOption } from "./Select";
export { ToastProvider, useToast } from "./Toast";
export {
  BodyText,
  Cap,
  Display,
  Eyebrow,
  Heading1,
  Heading2,
  Mono,
  SmallText,
  Sub,
} from "./Typography";
