/** GET /api/health — liveness probe (App Runner uses a TCP check; this is for local/manual checks). */

export const dynamic = "force-dynamic";

export function GET(): Response {
  return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
}
