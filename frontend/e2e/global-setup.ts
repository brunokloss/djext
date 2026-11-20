import { execSync } from "node:child_process";

const run = (command: string) =>
  execSync(`uv run python manage.py ${command}`, {
    cwd: "../backend",
    stdio: "inherit",
  });

// The login tests use the example users (password "password"). Both commands
// are safe to re-run, so this also works against an existing `make dev` database.
// The returned function is the teardown: it deletes the sessions this run
// created, which would otherwise pile up in that database.
export default function globalSetup() {
  const since = new Date().toISOString();
  run("migrate --verbosity 0");
  run("seed_users");
  return () => run(`clear_example_sessions --since ${since}`);
}
