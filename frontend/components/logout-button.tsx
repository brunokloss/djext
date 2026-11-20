"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTransition } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api/client";

export function LogoutButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function logout() {
    startTransition(async () => {
      await api.POST("/api/auth/logout");
      router.replace("/login");
    });
  }

  return (
    <Button
      variant="ghost"
      className="w-full justify-start"
      onClick={logout}
      disabled={pending}
    >
      <LogOut />
      Log out
    </Button>
  );
}
