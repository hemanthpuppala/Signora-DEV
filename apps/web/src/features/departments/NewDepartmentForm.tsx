"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";

import { api, unwrap } from "@/shared/api/client";
import { ApiError, fieldErrors, formError } from "@/shared/api/errors";
import { useIdempotentAction } from "@/shared/api/useIdempotentAction";
import { Button, HeadRow, Heading1, Notice, Section, TextArea, TextField } from "@/shared/ui";

import { type Department } from "./api";

type Input = { name: string; description: string };

/** Screen 06 (deviation: name and description only; the dropzone arrives with uploading). */
export function NewDepartmentForm() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const create = useIdempotentAction<Input, Department>("department-create", (input, key) =>
    unwrap(api.POST("/api/v1/departments", { body: input, headers: { "Idempotency-Key": key } })),
  );

  const created = create.state.status === "success" ? create.state.data : null;
  useEffect(() => {
    if (!created) return;
    void queryClient.invalidateQueries({ queryKey: ["departments"] });
    router.replace(`/departments/${created.id}`);
  }, [created, queryClient, router]);

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
    <form onSubmit={submit} noValidate>
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
        <div>
          <Button type="submit" arrow loading={create.isPending || Boolean(created)} loadingLabel="Creating…">
            Create department
          </Button>
        </div>
      </Section>
    </form>
  );
}
