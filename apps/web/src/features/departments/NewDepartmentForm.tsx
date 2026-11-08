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
 * Screen 06. With ``upload`` (people who can upload), a dropzone holds files in the browser until
 * the department exists (Phase 4 LLD §6.3); ``onCreated`` gets them, and the route decides where
 * to go (the upload page, which then uploads them).
 */
export function NewDepartmentForm({
  onCreated,
  upload,
}: {
  onCreated: (department: Department, files: File[]) => void;
  upload?: { hint: string } | undefined;
}) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const create = useIdempotentAction<Input, Department>("department-create", (input, key) =>
    unwrap(api.POST("/api/v1/departments", { body: input, headers: { "Idempotency-Key": key } })),
  );

  const created = create.state.status === "success" ? create.state.data : null;
  useEffect(() => {
    if (!created) return;
    void queryClient.invalidateQueries({ queryKey: ["departments"] });
    onCreated(created, files);
  }, [created, queryClient, onCreated, files]);

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
      <HeadRow>
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
        <Section title="Documents">
          {files.length > 0 ? (
            <TablePanel label="Documents to upload list">
              <table>
                <thead>
                  <tr>
                    <th>File</th>
                    <ActionHeader label="Remove" />
                  </tr>
                </thead>
                <tbody>
                  {files.map((file, index) => (
                    <tr key={`${file.name}-${index}`}>
                      <td>{file.name}</td>
                      <ActionCell>
                        <TextButton onClick={() => setFiles(files.filter((_, other) => other !== index))}>
                          Remove
                        </TextButton>
                      </ActionCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TablePanel>
          ) : null}
          <Dropzone
            title="Drop a PDF or Word file"
            hint={upload.hint}
            accept=".pdf,.docx"
            onFile={(file) => setFiles((current) => [...current, file])}
          />
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
