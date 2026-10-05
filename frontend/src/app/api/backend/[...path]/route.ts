import { getBackendApiUrl } from "@/lib/schemas/environment";

type ProxyContext = {
  params: Promise<{ path: string[] }>;
};

async function proxyRequest(request: Request, context: ProxyContext) {
  const { path } = await context.params;
  const destination = getBackendApiUrl();
  destination.pathname = path.map(encodeURIComponent).join("/");
  destination.search = new URL(request.url).search;

  const headers = new Headers();
  for (const name of ["accept", "content-type", "x-request-id"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const response = await fetch(destination, {
    method: request.method,
    headers,
    body:
      request.method === "GET" || request.method === "HEAD"
        ? undefined
        : await request.arrayBuffer(),
    cache: "no-store",
    redirect: "manual",
  });
  const responseHeaders = new Headers();
  for (const name of ["content-type", "x-request-id"]) {
    const value = response.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export {
  proxyRequest as DELETE,
  proxyRequest as GET,
  proxyRequest as PATCH,
  proxyRequest as POST,
  proxyRequest as PUT,
};
