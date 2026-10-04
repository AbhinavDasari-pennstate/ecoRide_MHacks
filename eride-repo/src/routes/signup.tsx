import { createFileRoute } from "@tanstack/react-router";
import { AuthForm, safeNext } from "@/components/AuthForm";
export const Route = createFileRoute("/signup")({
  validateSearch: (search: Record<string, unknown>) => ({ next: safeNext(search["next"]) }),
  head: () => ({ meta: [{ title: "Create account | eCARide" }] }),
  component: Signup,
});
function Signup() {
  const { next } = Route.useSearch();
  return <AuthForm signup next={next} />;
}
