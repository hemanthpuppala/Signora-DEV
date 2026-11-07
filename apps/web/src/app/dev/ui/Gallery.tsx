"use client";

import { useState } from "react";

import {
  BodyText,
  Button,
  Cap,
  Checkbox,
  Display,
  Eyebrow,
  Heading1,
  Heading2,
  MetricGrid,
  MetricTile,
  Mono,
  Notice,
  Radio,
  Select,
  SmallText,
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
  { value: "read", label: "Read" },
  { value: "read_write", label: "Read/write" },
];

/** Every Phase 1 component, for side-by-side comparison with docs/design-system/prototype.html. */
export function Gallery() {
  const toast = useToast();
  const [access, setAccess] = useState<string | null>("read");
  const [loading, setLoading] = useState(false);

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
          <Button arrow>Create workspace</Button>
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
        <Select label="Workspace access" options={ACCESS} value={access} onChange={setAccess} />
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
        <TablePanel>
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
    </>
  );
}
