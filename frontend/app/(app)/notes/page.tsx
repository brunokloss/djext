import { serverApi } from "@/lib/api/server";
import { Notes } from "./notes";

export const instant = false;

// The example feature (backend/apps/note): copy it, then delete it.
// Reads the notes on the server, so the page arrives with them.
export default async function NotesPage() {
  const { data } = await (await serverApi()).GET("/api/notes");

  return (
    <>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Notes</h1>
        <p className="text-sm text-muted-foreground">
          An example feature, from the model to this page. See
          backend/apps/note/README.md.
        </p>
      </div>
      <Notes initial={data} />
    </>
  );
}
