"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useIdempotencyKey } from "@/lib/api/idempotency";

// The parts of the Notes page you click. They write through the Next proxy
// with api.POST/DELETE (session cookie and CSRF, like any browser call), then
// router.refresh() renders the Server Component again with the new list. The
// POSTs carry an Idempotency-Key, so a double click or a retry doesn't create
// the note (or send the email) twice.

export function NewNote() {
  const router = useRouter();
  const idem = useIdempotencyKey();
  const [error, create, pending] = useActionState(
    async (_previous: string | null, form: FormData) => {
      const { error, response } = await api.POST("/api/notes", {
        body: {
          title: String(form.get("title")),
          body: String(form.get("body")),
        },
        headers: idem.headers,
      });
      idem.settle(response);
      if (error) return "Could not save the note.";
      router.refresh();
      return null;
    },
    null,
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle>New note</CardTitle>
      </CardHeader>
      <CardContent>
        <form action={create} className="flex flex-col gap-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="title">Title</Label>
            <Input id="title" name="title" maxLength={200} required />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="body">Text</Label>
            <Textarea id="body" name="body" rows={3} />
          </div>
          {error && (
            <p role="alert" className="text-sm text-destructive">
              {error}
            </p>
          )}
          <Button type="submit" disabled={pending}>
            Add note
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export function NoteActions({ id }: { id: string }) {
  const router = useRouter();
  const idem = useIdempotencyKey();
  const [emailed, setEmailed] = useState(false);
  const [deleting, startDelete] = useTransition();
  const path = { note_id: id };

  async function email() {
    const { response } = await api.POST("/api/notes/{note_id}/email", {
      params: { path },
      headers: idem.headers,
    });
    idem.settle(response);
    setEmailed(response.ok);
  }

  function remove() {
    startDelete(async () => {
      await api.DELETE("/api/notes/{note_id}", { params: { path } });
      router.refresh();
    });
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={email}>
        {emailed ? "Emailed" : "Email me"}
      </Button>
      <Button variant="ghost" size="sm" onClick={remove} disabled={deleting}>
        Delete
      </Button>
    </>
  );
}
