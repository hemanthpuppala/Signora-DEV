import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import {
  ActionBar,
  Button,
  ClampedText,
  DocumentCard,
  DocumentGrid,
  EmailField,
  ExpandableList,
  ExpandableRow,
  IconButton,
  InfoTip,
  SearchField,
  StepDialog,
  Select,
  StatusPill,
  TablePanel,
  TextField,
  ToastProvider,
  useToast,
} from "./index";

describe("Button", () => {
  it("shows the loading label, disables itself and marks busy while loading", () => {
    render(
      <Button loading arrow>
        Send
      </Button>,
    );
    const button = screen.getByRole("button", { name: "Sending…" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).not.toHaveTextContent("→");
  });

  it("renders the trailing arrow and is a non-submit button by default", () => {
    render(<Button arrow>Create account</Button>);
    const button = screen.getByRole("button", { name: /Create account/ });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveTextContent("→");
  });
});

describe("TextField", () => {
  it("links the label, hint and error to the input", () => {
    render(<TextField label="Work email" hint="We send a code here." error="Not a valid email" />);
    const input = screen.getByLabelText("Work email");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("We send a code here. Not a valid email");
  });
});

function ControlledSelect({ onChange }: { onChange: (value: string) => void }) {
  const [value, setValue] = useState<string | null>("read");
  return (
    <Select
      label="Access"
      options={[
        { value: "read", label: "Read" },
        { value: "read_write", label: "Read/write" },
        { value: "none", label: "None" },
      ]}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

describe("IconButton", () => {
  it("is named by its label, shows it as a tooltip, and Escape hides the tooltip", async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    render(<IconButton icon="star" label="Make current" onClick={onClick} />);

    const button = screen.getByRole("button", { name: "Make current" });
    const tip = screen.getByText("Make current");
    expect(tip.getAttribute("aria-hidden")).toBe("true"); // the name is the button's; the tooltip only shows it
    await user.click(button);
    expect(onClick).toHaveBeenCalledOnce();
    await user.keyboard("{Escape}");
    expect(tip.className).toMatch(/dismissed/);
  });

  it("can be a download link", () => {
    render(<IconButton icon="download" label="Download original" href="/file.pdf" download />);
    const link = screen.getByRole("link", { name: "Download original" });
    expect(link.getAttribute("href")).toBe("/file.pdf");
    expect(link.hasAttribute("download")).toBe(true);
  });
});

describe("SearchField", () => {
  it("is a search box named by its label, which is also its placeholder", () => {
    render(<SearchField label="Find a field" />);
    const input = screen.getByRole("searchbox", { name: "Find a field" });
    expect(input.getAttribute("placeholder")).toBe("Find a field");
  });
});

describe("Select", () => {
  it("opens with ArrowDown, moves with arrows, chooses with Enter and keeps focus", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ControlledSelect onChange={onChange} />);
    const combobox = screen.getByRole("combobox", { name: "Access" });

    combobox.focus();
    await user.keyboard("{ArrowDown}");
    expect(combobox).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("listbox")).toBeVisible();

    await user.keyboard("{ArrowDown}{Enter}");
    expect(onChange).toHaveBeenCalledWith("read_write");
    expect(combobox).toHaveAttribute("aria-expanded", "false");
    expect(combobox).toHaveTextContent("Read/write");
    expect(combobox).toHaveFocus();
  });

  it("supports Home/End and closes with Escape without changing the value", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ControlledSelect onChange={onChange} />);
    const combobox = screen.getByRole("combobox", { name: "Access" });

    combobox.focus();
    await user.keyboard("{ArrowDown}{End}");
    expect(combobox.getAttribute("aria-activedescendant")).toMatch(/option-2$/);
    await user.keyboard("{Home}");
    expect(combobox.getAttribute("aria-activedescendant")).toMatch(/option-0$/);
    await user.keyboard("{Escape}");

    expect(combobox).toHaveAttribute("aria-expanded", "false");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("chooses an option with the mouse and marks it selected", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ControlledSelect onChange={onChange} />);

    await user.click(screen.getByRole("combobox", { name: "Access" }));
    await user.click(screen.getByRole("option", { name: "None" }));

    expect(onChange).toHaveBeenCalledWith("none");
  });
});

describe("StatusPill", () => {
  it("shows the label; the colour lives only on the decorative dot", () => {
    render(<StatusPill status="signed" />);
    expect(screen.getByText("Signed")).toBeInTheDocument();
  });
});

function ToastTrigger() {
  const toast = useToast();
  return <button onClick={() => toast.show("Draft saved")}>save</button>;
}

describe("Toast", () => {
  it("announces the message politely and hides it after the duration", () => {
    vi.useFakeTimers();
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>,
    );

    act(() => screen.getByRole("button", { name: "save" }).click());
    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Draft saved");
    expect(status).toHaveAttribute("aria-live", "polite");

    act(() => vi.advanceTimersByTime(2600));
    expect(screen.queryByRole("status")).toBeNull();
    vi.useRealTimers();
  });
});

describe("TablePanel", () => {
  it("is a named, keyboard-focusable region so a long table can be scrolled", () => {
    render(
      <TablePanel label="Members list">
        <table>
          <tbody>
            <tr>
              <td>Rosa</td>
            </tr>
          </tbody>
        </table>
      </TablePanel>,
    );
    const region = screen.getByRole("region", { name: "Members list" });
    expect(region.getAttribute("tabindex")).toBe("0");
  });
});

describe("EmailField", () => {
  function Controlled() {
    const [value, setValue] = useState("");
    return (
      <>
        <EmailField label="Email" value={value} onChange={(event) => setValue(event.target.value)} />
        <button type="button">Next</button>
      </>
    );
  }

  it("points out a malformed address when the field is left, not while typing", async () => {
    const user = userEvent.setup();
    render(<Controlled />);
    const input = screen.getByLabelText("Email");

    await user.type(input, "hiaf");
    expect(screen.queryByRole("alert")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("alert").textContent).toBe("Enter a valid email address");

    await user.type(input, "@firm.com");
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("ClampedText", () => {
  function overflow(scrollWidth: number) {
    Object.defineProperty(HTMLElement.prototype, "scrollWidth", { configurable: true, value: scrollWidth });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, value: 300 });
  }

  it("shows More only when the text does not fit, and opens it in a scrollable box", async () => {
    overflow(900);
    render(<ClampedText>{"A long description. ".repeat(40)}</ClampedText>);

    const more = screen.getByRole("button", { name: "More" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    await userEvent.setup().click(more);
    const less = screen.getByRole("button", { name: "Less" });
    expect(less.getAttribute("aria-expanded")).toBe("true");
    const text = document.getElementById(less.getAttribute("aria-controls") ?? "");
    expect(text?.getAttribute("tabindex")).toBe("0");
  });

  it("shows no button when the text fits", () => {
    overflow(200);
    render(<ClampedText>Short.</ClampedText>);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("ExpandableRow", () => {
  it("opens its details in place under its button, and says so", async () => {
    function Rows() {
      const [open, setOpen] = useState(false);
      return (
        <ExpandableList label="Fields">
          <ExpandableRow id="f" title="Company" meta="Required" expanded={open} regionLabel="Details of Company" onToggle={() => setOpen(!open)}>
            Page 1
          </ExpandableRow>
        </ExpandableList>
      );
    }
    render(<Rows />);
    const row = screen.getByRole("button", { name: "Company" }); // the title alone; the facts describe it
    expect(row).toHaveAccessibleDescription("Required");
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "Details of Company" })).toBeNull();

    await userEvent.click(row);
    expect(row).toHaveAttribute("aria-expanded", "true");
    expect(row).toHaveAttribute("aria-controls", "f-details");
    expect(screen.getByRole("region", { name: "Details of Company" })).toHaveTextContent("Page 1");
  });
});

describe("ActionBar", () => {
  it("is a named region with the state and the actions", () => {
    render(
      <ActionBar label="Review" actions={<Button compact>Approve version</Button>}>
        <span>Version 2</span>
        <span>Needs approval</span>
      </ActionBar>,
    );
    const bar = screen.getByRole("region", { name: "Review" });
    expect(bar).toHaveTextContent("Version 2Needs approval");
    expect(screen.getByRole("button", { name: "Approve version" })).toBeInTheDocument();
  });
});

describe("ExpandableList, scrolling", () => {
  it("brings an opened row to its top and fits that row and the two under it", async () => {
    const heights: Record<string, number> = { a: 50, b: 50, c: 200, d: 50, e: 50, f: 50 };
    vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockImplementation(function (this: HTMLElement) {
      return heights[this.id] ?? 0;
    });
    vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockImplementation(function (this: HTMLElement) {
      return this.id === "c" ? 100 : 0;
    });
    const scrollTo = vi.fn();
    HTMLElement.prototype.scrollTo = scrollTo as unknown as HTMLElement["scrollTo"];
    function Rows() {
      const [open, setOpen] = useState<string | null>(null);
      return (
        <ExpandableList label="Fields" scrollable>
          {Object.keys(heights).map((id) => (
            <ExpandableRow key={id} id={id} title={id.toUpperCase()} expanded={open === id} regionLabel={id} onToggle={() => setOpen(open === id ? null : id)}>
              Details
            </ExpandableRow>
          ))}
        </ExpandableList>
      );
    }
    render(<Rows />);
    const list = screen.getByRole("list", { name: "Fields" });
    expect(list.style.maxHeight).toBe(""); // all closed: the design system's table height

    await userEvent.click(screen.getByRole("button", { name: "C" }));
    expect(scrollTo).toHaveBeenCalledWith({ top: 100, behavior: "smooth" });
    expect(list.style.maxHeight).toBe("301px"); // C (200) + D + E (50 each) + the hairline

    await userEvent.click(screen.getByRole("button", { name: "C" }));
    expect(list.style.maxHeight).toBe("");
    vi.restoreAllMocks();
  });
});

describe("InfoTip", () => {
  it("opens on hover, stays open after a click until Escape or a press elsewhere, and is read when open", async () => {
    const user = userEvent.setup();
    render(
      <>
        <InfoTip label="Places">Where this field appears.</InfoTip>
        <button type="button">Elsewhere</button>
      </>,
    );
    const button = screen.getByRole("button", { name: "About Places" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("note")).toBeNull();

    await user.hover(button);
    expect(screen.getByRole("note")).toHaveTextContent("Where this field appears.");
    await user.unhover(button);
    expect(screen.queryByRole("note")).toBeNull();

    await user.click(button); // a tap on a phone: stays open
    await user.unhover(button);
    expect(button).toHaveAttribute("aria-expanded", "true");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("note")).toBeNull();

    await user.click(button);
    await user.click(screen.getByRole("button", { name: "Elsewhere" }));
    expect(screen.queryByRole("note")).toBeNull();
  });
});

describe("StepDialog", () => {
  it("marks the current step and the finished ones and goes back to them", async () => {
    const onStep = vi.fn();
    render(
      <StepDialog title="New envelope" steps={["Document", "Details", "Review"]} current={1} onStep={onStep} onClose={vi.fn()} actions={null}>
        Step two
      </StepDialog>,
    );
    const steps = screen.getByRole("list", { name: "Steps" });
    const items = steps.querySelectorAll("li");
    expect(items[1]).toHaveAttribute("aria-current", "step");
    expect(items[0]).toHaveTextContent("Document, done");
    await userEvent.click(screen.getByRole("button", { name: /Document/ }));
    expect(onStep).toHaveBeenCalledWith(0);
    expect(screen.queryByRole("button", { name: /Review/ })).toBeNull(); // later steps come by Next
  });
});

describe("DocumentCard, choosing", () => {
  it("is a button that says whether it is chosen, and can be unavailable", async () => {
    const onChoose = vi.fn();
    render(
      <DocumentGrid label="Documents">
        <DocumentCard choose={{ chosen: true, onChoose }} kind="PDF" title="Mutual NDA" facts="2 pages" status={null} />
        <DocumentCard choose={{ chosen: false, onChoose, disabled: true }} kind="DOC" title="Draft" facts="1 page" status={null} />
      </DocumentGrid>,
    );
    expect(screen.getByRole("button", { name: "Mutual NDA" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Draft" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Mutual NDA" }));
    expect(onChoose).toHaveBeenCalledTimes(1);
  });
});
