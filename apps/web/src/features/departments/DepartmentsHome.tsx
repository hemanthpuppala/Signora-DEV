"use client";

import { useSearchParams } from "next/navigation";

import { formError } from "@/shared/api/errors";
import { CONSOLE_HOME } from "@/shared/lib/routes";
import { can, type Me } from "@/shared/session";
import {
  AddCard,
  BodyText,
  CardGrid,
  HeadRow,
  Heading1,
  LinkButton,
  Notice,
  StatCard,
  Tabs,
} from "@/shared/ui";

import { useDepartments, type DepartmentStatus } from "./api";

/** Screen 05: the company's departments (home of the console). */
export function DepartmentsHome({ me }: { me: Me }) {
  const status: DepartmentStatus = useSearchParams().get("status") === "archived" ? "archived" : "active";
  const departments = useDepartments(status);
  const canCreate = can(me, "departments.create");

  // Actions a person cannot take are not shown at all (design-system principle 5).
  const action = canCreate ? (
    <LinkButton href="/departments/new" arrow>
      New department
    </LinkButton>
  ) : null;

  const list = departments.data ?? [];
  return (
    <>
      <HeadRow actions={action}>
        <Heading1>Departments</Heading1>
      </HeadRow>
      <Tabs
        label="Department status"
        items={[
          { href: CONSOLE_HOME, label: "Active", active: status === "active" },
          { href: `${CONSOLE_HOME}?status=archived`, label: "Archived", active: status === "archived" },
        ]}
      />
      {departments.isError ? <Notice tone="warning">{formError(departments.error)}</Notice> : null}
      {departments.isSuccess && list.length === 0 ? (
        <BodyText>
          {status === "archived"
            ? "No archived departments."
            : canCreate
              ? "Create your first department, for example Finance or Client Intake."
              : "No departments yet."}
        </BodyText>
      ) : null}
      {list.length > 0 || (canCreate && status === "active" && departments.isSuccess) ? (
        <CardGrid label={status === "archived" ? "Archived departments" : "Departments"}>
          {list.map((department) => (
            <StatCard
              key={department.id}
              href={`/departments/${department.id}`}
              title={department.name}
              description={department.description}
              stats={[
                { label: "Sent", value: department.counts.sent },
                { label: "Signed", value: department.counts.signed },
                { label: "Pending", value: department.counts.pending },
              ]}
            />
          ))}
          {canCreate && status === "active" ? <AddCard href="/departments/new" label="New department" /> : null}
        </CardGrid>
      ) : null}
    </>
  );
}
