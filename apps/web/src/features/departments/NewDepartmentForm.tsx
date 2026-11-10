"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import {
  ActionCell,
  ActionHeader,
  Button,
  Dropzone,
  HeadRow,
  Heading1,
  Notice,
  PageForm,
  Section,
  TablePanel,
  TextArea,
  TextButton,
  TextField,
} from "@/shared/ui";

import { type Department } from "./api";

type Input = { name: string; description: string };

/**
 * Screen 06. With ``upload`` (people who can upload), a dropzone holds one file in the browser
 * until the department exists (Phase 4 LLD §6.3); ``onCreated`` gets it, and the route decides
 * where to go (the upload page, which then uploads it).
 */
export function NewDepartmentForm({
  onCreated,
  upload,
}: {
  onCreated: (department: Department, file: File | null) => void;
  upload?: { hint: string } | undefined;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const create = useIdempotentAction<Input, Department>("department-create", (input, key) =>
    unwrap(api.POST("/api/v1/departments", { body: input, headers: { "Idempotency-Key": key } })),
  );

  const created = create.state.status === "success" ? create.state.data : null;
  useEffect(() => {
    if (!created) return;
    void queryClient.invalidateQueries({ queryKey: ["departments"] });
    onCreated(created, file);
  }, [created, queryClient, onCreated, file]);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    create.run({ name, description });
  };
  const error = create.state.error;
  const nameTaken = error instanceof ApiError && error.code === "department-name-taken";
  const errors = fieldErrors(error);
  const problem =
    create.state.status === "retrying" ? "Connection lost — retrying…" : nameTaken ? null : formError(error);
  return (
    <PageForm onSubmit={submit} noValidate>
      <HeadRow back={{ href: "/", label: "Departments" }}>
        <Heading1>New department</Heading1>
      </HeadRow>
      <Section title="About">
        {problem ? <Notice tone="warning">{problem}</Notice> : null}
        <TextField
          label="Name"
          required
          maxLength={80}
          value={name}
          error={nameTaken ? "Another department already has this name." : errors.name}
          onChange={(event) => setName(event.target.value)}
        />
        <TextArea
          label="Description"
          maxLength={500}
          value={description}
          error={errors.description}
          onChange={(event) => setDescription(event.target.value)}
        />
      </Section>
      {upload ? (
        <Section title="Templates">
          {/* One document at a time: the dropzone until a file is chosen, then the file in its place. */}
          {file ? (
            <TablePanel label="Template to upload">
              <table>
                <thead>
                  <tr>
                    <th>File</th>
                    <ActionHeader label="Remove" />
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>{file.name}</td>
                    <ActionCell>
                      <TextButton onClick={() => setFile(null)}>Remove</TextButton>
                    </ActionCell>
                  </tr>
                </tbody>
              </table>
            </TablePanel>
          ) : (
            <Dropzone title="Drop a PDF or Word file" hint={upload.hint} accept=".pdf,.docx" onFile={setFile} />
          )}
        </Section>
      ) : null}
      <div>
        <Button type="submit" arrow loading={create.isPending || Boolean(created)} loadingLabel="Creating…">
          Create department
        </Button>
      </div>
    </PageForm>
  );
}
