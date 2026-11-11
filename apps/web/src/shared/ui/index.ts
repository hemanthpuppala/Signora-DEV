/** Design-system components (single source of styling; backbone LLD §8.6). */
export { ActionBar } from "./ActionBar";
export { AppShell, TopBar, type AppShellProps, type NavItem, type TopBarProps } from "./AppShell";
export { SignatureLogo } from "./SignatureLogo";
export { AuthPanel, type AuthPanelProps } from "./AuthPanel";
export {
  Button,
  LinkButton,
  TextButton,
  type ButtonProps,
  type ButtonVariant,
  HeadAction,
} from "./Button";
export { Checkbox, Radio } from "./Choice";
export { CodeField, type CodeFieldProps } from "./CodeField";
export { Chip, ChipGroup } from "./Chip";
export {
  ActionCell,
  ActionHeader,
  MetricGrid,
  MetricTile,
  MetaLine,
  Notice,
  STATUSES,
  StatusPill,
  TablePanel,
  Tabs,
  type Status,
  type TabItem,
} from "./Display";
export { Calendar, DatePicker, dateInWords, type DatePickerProps } from "./DatePicker";
export { Dialog } from "./Dialog";
export { GuidePointer } from "./GuidePointer";
export { Menu, type MenuItem } from "./Menu";
export { StepDialog } from "./StepDialog";
export { Dropzone } from "./Dropzone";
export { ExpandableList, ExpandableRow } from "./Expandable";
export { EmailField, type EmailFieldProps } from "./EmailField";
export { SearchField, TextArea, TextField } from "./Field";
export { Icon, type IconName } from "./Icon";
export { InfoTip } from "./InfoTip";
export { IconButton, Tooltip, type IconButtonProps } from "./Tooltip";
export { FactList, type Fact } from "./FactList";
export { Item, ItemAction, ItemActions, ItemHead, ItemList } from "./ItemList";
export {
  BackLink,
  Block,
  Blocks,
  DetailsPane,
  FieldAction,
  FieldGrid,
  HeadRow,
  PageForm,
  Section,
  ViewerLayout,
  ViewerPane,
  type Back,
} from "./Layout";
export { AddCard, CardGrid, StatCard, type CardStat } from "./Card";
export { DocumentCard, DocumentGrid } from "./DocumentCard";
export { ClampedText } from "./ClampedText";
export { RowActions } from "./RowActions";
export { PasswordField, type PasswordFieldProps } from "./PasswordField";
export { PdfViewer, type PdfOverlayArgs, type PdfViewerProps } from "./pdf/PdfViewer";
export { Select, type SelectOption } from "./Select";
export { PAD_HEIGHT, PAD_WIDTH, SignaturePad, type Stroke } from "./SignaturePad";
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
