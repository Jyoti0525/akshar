"use client";

import { useRouter } from "next/navigation";
import { Button } from "./ui/button";

export function SignOut() {
  const router = useRouter();
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={async () => {
        await fetch("/api/session", { method: "DELETE" });
        router.replace("/login");
        router.refresh();
      }}
    >
      Sign out
    </Button>
  );
}
