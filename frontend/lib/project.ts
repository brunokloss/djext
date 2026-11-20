// The project's names, so a fork sets envs instead of editing these files.
// NEXT_PUBLIC_: read when the app is built (in the browser bundle too), so
// set them before `next build`.

// PROJECT_SLUG in backend/.env: the cookie names start with it.
export const projectSlug = process.env.NEXT_PUBLIC_PROJECT_SLUG || "djext";

// The name people see (title, sidebar, login page).
export const projectName = process.env.NEXT_PUBLIC_PROJECT_NAME || projectSlug;
