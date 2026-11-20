import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { LoginForm } from "@/components/login-form";
import { api } from "@/lib/api/client";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/api/client", () => ({ api: { POST: vi.fn() } }));

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function submit() {
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: "ana@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "s3cret" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Log in" }));
}

test("logs in and goes to the home page", async () => {
  vi.mocked(api.POST).mockResolvedValue({
    data: {},
    error: undefined,
    response: new Response(),
  } as never);
  render(<LoginForm />);
  submit();
  await vi.waitFor(() => expect(replace).toHaveBeenCalledWith("/"));
  expect(api.POST).toHaveBeenCalledWith("/api/auth/login", {
    body: { email: "ana@example.com", password: "s3cret" },
  });
});

test("shows the error from the API", async () => {
  vi.mocked(api.POST).mockResolvedValue({
    data: undefined,
    error: { detail: "Invalid email or password" },
    response: new Response(null, { status: 401 }),
  } as never);
  render(<LoginForm />);
  submit();
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Invalid email or password",
  );
  expect(replace).not.toHaveBeenCalled();
  expect(screen.getByLabelText<HTMLInputElement>("Email").value).toBe(
    "ana@example.com",
  );
});
