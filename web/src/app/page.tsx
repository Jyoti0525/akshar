import { redirect } from "next/navigation";
import { cookies } from "next/headers";
import { ROLE_COOKIE } from "@/lib/api/session";

/**
 * There is no home page, deliberately. Section 11 gives every role a first
 * screen: a supervisor opens the dashboard, an officer opens the scanner. A
 * landing page between the two would be a click every user pays every morning.
 */
export default async function Home() {
  const role = (await cookies()).get(ROLE_COOKIE)?.value;
  redirect(role === "supervisor" || role === "admin" ? "/dashboard" : "/scan");
}
