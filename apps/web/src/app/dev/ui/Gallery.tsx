"use client";

import { useState } from "react";

import {
  ActionBar,
  BodyText,
  Button,
  Cap,
  Checkbox,
  Chip,
  ChipGroup,
  Display,
  Eyebrow,
  ExpandableList,
  ExpandableRow,
  Heading1,
  Heading2,
  InfoTip,
  MetricGrid,
  MetricTile,
  Mono,
  Notice,
  Radio,
  SearchField,
  Select,
  SmallText,
  StepDialog,
  STATUSES,
  StatusPill,
  Sub,
  TablePanel,
  Tabs,
  TextArea,
  TextButton,
  TextField,
  useToast,
} from "@/shared/ui";

import styles from "./gallery.module.css";

const ACCESS = [
  { value: "read", label: "Viewer" },
  { value: "read_write", label: "Editor" },
];

/** Every Phase 1 component, for side-by-side comparison with docs/design-system/prototype.html. */
export function Gallery() {
  const toast = useToast();
  const [access, setAccess] = useState<string | null>("read");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<string | null>("company");
  const [place, setPlace] = useState(0);
  const [step, setStep] = useState<number | null>(null);

  return (
    <>
      <section className={styles.section}>
        <Eyebrow>Typography</Eyebrow>
        <Display>Every file starts with a signature.</Display>
        <Heading1>Good morning, Hemanth.</Heading1>
        <Heading2>Three steps, in order.</Heading2>
        <Sub>For firms that would rather not chase one.</Sub>
        <BodyText>
          Upload your client agreement once. Signora finds every field and every party.
        </BodyText>
        <SmallText>Small supporting text.</SmallText>
        <div className={styles.row}>
          <Cap>← Projects</Cap>
          <Mono>sha256 9f2c…e41a</Mono>
        </div>
      </section>

      <section className={styles.section}>
        <Eyebrow>Buttons</Eyebrow>
        <div className={styles.row}>
          <Button arrow>Create account</Button>
          <Button variant="quiet">Review and sign</Button>
          <Button variant="destructive">Cancel envelope</Button>
          <Button loading={loading} onClick={() => setLoading(true)}>
            Send
          </Button>
          <Button disabled>Disabled</Button>
          <TextButton onClick={() => toast.show("Draft saved")}>Save draft</TextButton>
        </div>
      </section>

      <section className={styles.section}>
        <Eyebrow>Fields</Eyebrow>
        <TextField label="Work email" type="email" placeholder="name@example.com" hint="We send a code here." />
        <TextField label="Password" type="password" error="At least 12 characters." />
        <TextArea label="Description for the detector (optional)" />
        <SearchField label="Find a field" />
        <Select label="Invite as" options={ACCESS} value={access} onChange={setAccess} />
        <Checkbox defaultChecked>I agree to use electronic records and signatures.</Checkbox>
        <Radio name="wait" defaultChecked>
          Anyone
        </Radio>
        <Radio name="wait">A client</Radio>
      </section>

      <section className={styles.section}>
        <Eyebrow>Status</Eyebrow>
        <div className={styles.row}>
          {STATUSES.map((status) => (
            <StatusPill key={status} status={status} />
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <Eyebrow>Metrics, notices, tabs, table</Eyebrow>
        <MetricGrid>
          <MetricTile value={61} label="Sent this month" />
          <MetricTile value={48} label="Completed" />
          <MetricTile value={9} label="Pending" />
        </MetricGrid>
        <Notice title="Your turn" action={<Button variant="quiet">Review and sign</Button>}>
          Chen v. Northwind needs your countersignature.
        </Notice>
        <Notice tone="warning" title="Email not delivered">
          Receipt to leo.chen@example.com failed after 5 tries.
        </Notice>
        <Tabs
          label="Project sections"
          items={[
            { href: "/dev/ui", label: "Envelopes", active: true },
            { href: "/dev/ui#documents", label: "Documents · 3" },
          ]}
        />
        <TablePanel label="Example table">
          <table>
            <thead>
              <tr>
                <th>Matter</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Chen v. Northwind</td>
                <td>
                  <StatusPill status="signed" />
                </td>
              </tr>
            </tbody>
          </table>
        </TablePanel>
      </section>

      <section className={styles.section}>
        <div className={styles.row}>
          <Eyebrow>Action bar, rows that open in place</Eyebrow>
          <InfoTip label="this section">
            <span>What a section is for, in a line or two.</span>
            <span>
              <strong>A button</strong>: what it does, when its name does not say it all.
            </span>
          </InfoTip>
        </div>
        <ActionBar label="Review" actions={<Button compact>Approve version</Button>}>
          <span>Version 2</span>
          <span>Needs approval</span>
          <span>1 thing to check</span>
        </ActionBar>
        <div className={styles.row}>
          <Button variant="quiet" compact icon="plus">
            Add a place
          </Button>
          <Button variant="quiet" compact icon="pages">
            On every page
          </Button>
          <Button variant="destructive" compact icon="trash">
            Delete field
          </Button>
        </div>
        <ChipGroup label="Places">
          {["1 · Page 1", "2 · Page 1", "3 · Page 4"].map((words, index) => (
            <Chip key={words} selected={place === index} onClick={() => setPlace(index)}>
              {words}
            </Chip>
          ))}
        </ChipGroup>
        <div className={styles.row}>
          <Button variant="quiet" compact onClick={() => setStep(0)}>
            Open a step dialog
          </Button>
        </div>
        {step !== null ? (
          <StepDialog
            title="New envelope"
            steps={["Document", "Details", "Review"]}
            current={step}
            onStep={setStep}
            onClose={() => setStep(null)}
            back={step > 0 ? <TextButton onClick={() => setStep(step - 1)}>Back</TextButton> : null}
            actions={
              <Button compact onClick={() => (step < 2 ? setStep(step + 1) : setStep(null))}>
                {step < 2 ? "Next" : "Done"}
              </Button>
            }
          >
            <SmallText>{`Step ${step + 1}: one part of the task at a time.`}</SmallText>
          </StepDialog>
        ) : null}
        <ExpandableList label="Fields">
          <ExpandableRow id="gallery-add" tone="add" title="Add field" expanded={false} regionLabel="New field" onToggle={() => undefined} />
          {[
            { id: "company", title: "Company", meta: "Filled in before sending · Company · Required" },
            { id: "signature", title: "Client signature", meta: "Client · Signature · Required" },
          ].map((row) => (
            <ExpandableRow
              key={row.id}
              id={`gallery-${row.id}`}
              title={row.title}
              meta={row.meta}
              expanded={open === row.id}
              regionLabel={`Details of ${row.title}`}
              onToggle={() => setOpen(open === row.id ? null : row.id)}
            >
              <SmallText>Page 1</SmallText>
            </ExpandableRow>
          ))}
        </ExpandableList>
      </section>
    </>
  );
}
