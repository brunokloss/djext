"use client";

import { useActionState, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api/client";
import { useApi } from "@/lib/api/hooks";
import { useIdempotencyKey } from "@/lib/api/idempotency";
import type { components } from "@/lib/api/schema";

type Note = components["schemas"]["NoteOut"];

// Reads with useApi (SWR), writes with api.POST/DELETE, then asks SWR to read
// the list again. The POSTs carry an Idempotency-Key, so a double click or a
// retry doesn't create the note (or send the email) twice.
export function Notes() {
  const { data: notes, error, mutate } = useApi("/api/notes");

  if (error) return <p role="alert">Could not load the notes.</p>;
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <NewNote onCreated={() => mutate()} />
      {notes?.map((note) => (
        <NoteCard key={note.id} note={note} onDeleted={() => mutate()} />
      ))}
    </div>
  );
}

function NewNote({ onCreated }: { onCreated: () => void }) {
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
      onCreated();
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

function NoteCard({ note, onDeleted }: { note: Note; onDeleted: () => void }) {
  const idem = useIdempotencyKey();
  const [emailed, setEmailed] = useState(false);
  const path = { note_id: note.id };

  async function email() {
    const { response } = await api.POST("/api/notes/{note_id}/email", {
      params: { path },
      headers: idem.headers,
    });
    idem.settle(response);
    setEmailed(response.ok);
  }

  async function remove() {
    await api.DELETE("/api/notes/{note_id}", { params: { path } });
    onDeleted();
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{note.title}</CardTitle>
        <CardDescription>
          {new Date(note.created_at).toLocaleString()}
        </CardDescription>
        <CardAction className="flex gap-2">
          <Button variant="outline" size="sm" onClick={email}>
            {emailed ? "Emailed" : "Email me"}
          </Button>
          <Button variant="ghost" size="sm" onClick={remove}>
            Delete
          </Button>
        </CardAction>
      </CardHeader>
      {note.body && (
        <CardContent className="whitespace-pre-wrap text-sm">
          {note.body}
        </CardContent>
      )}
    </Card>
  );
}
