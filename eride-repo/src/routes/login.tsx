import { createFileRoute } from "@tanstack/react-router";
import { AuthForm, safeNext } from "@/components/AuthForm";
export const Route = createFileRoute("/login")({
  validateSearch: (search: Record<string, unknown>) => ({ next: safeNext(search["next"]) }),
  head: () => ({ meta: [{ title: "Sign in | eCARide" }] }),
  component: Login,
});
function Login() {
  const { next } = Route.useSearch();
  return <AuthForm signup={false} next={next} />;
}
