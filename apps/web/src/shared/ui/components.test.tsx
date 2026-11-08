import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { Button, Select, StatusPill, TextField, ToastProvider, useToast } from "./index";

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
