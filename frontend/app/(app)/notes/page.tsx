import { Notes } from "./notes";

// The example feature (backend/apps/note): copy it, then delete it.
export default function NotesPage() {
  return (
    <>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
        <p className="text-sm text-muted-foreground">
          An example feature, from the model to this page. See
          backend/apps/note/README.md.
        </p>
      </div>
      <Notes />
    </>
  );
}
