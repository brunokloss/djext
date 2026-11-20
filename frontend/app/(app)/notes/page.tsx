import { LocalTime } from "@/components/local-time";
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { serverApi } from "@/lib/api/server";
import { NewNote, NoteActions } from "./note-forms";

export const instant = false;

// The example feature (backend/apps/note): copy it, then delete it.
// A Server Component: it reads the notes on the server and renders them, so
// the page arrives complete and ships no JavaScript for the list. Only the
// parts you click are Client Components (note-forms.tsx); after a write they
// call router.refresh() and this page renders again with the new list.
export default async function NotesPage() {
  const { data: notes } = await (await serverApi()).GET("/api/notes");

  return (
    <>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
        <p className="text-sm text-muted-foreground">
          An example feature, from the model to this page. See
          backend/apps/note/README.md.
        </p>
      </div>
      {notes ? (
        <div className="grid gap-4 md:grid-cols-2">
          <NewNote />
          {notes.map((note) => (
            <Card key={note.id}>
              <CardHeader>
                <CardTitle>{note.title}</CardTitle>
                <CardDescription>
                  <LocalTime value={note.created_at} />
                </CardDescription>
                <CardAction className="flex gap-2">
                  <NoteActions id={note.id} />
                </CardAction>
              </CardHeader>
              {note.body && (
                <CardContent className="whitespace-pre-wrap text-sm">
                  {note.body}
                </CardContent>
              )}
            </Card>
          ))}
        </div>
      ) : (
        <p role="alert">Could not load the notes.</p>
      )}
    </>
  );
}
