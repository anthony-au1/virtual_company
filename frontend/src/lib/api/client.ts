const API_PROXY_BASE_URL = "/api/backend";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly payload: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type ValidationDetail = {
  loc?: Array<string | number>;
  msg?: string;
};

export function apiErrorMessages(error: unknown): string[] {
  if (!(error instanceof ApiError)) {
    return [error instanceof Error ? error.message : "Request failed."];
  }

  if (
    error.payload &&
    typeof error.payload === "object" &&
    "detail" in error.payload
  ) {
    const { detail } = error.payload;
    if (typeof detail === "string") return [detail];
    if (Array.isArray(detail)) {
      const messages = detail.flatMap((item: ValidationDetail) => {
        if (typeof item?.msg !== "string") return [];
        const path = (item.loc ?? [])
          .filter((part) => part !== "body")
          .map(String)
          .join(" → ");
        return [path ? `${path}: ${item.msg}` : item.msg];
      });
      if (messages.length) return messages;
    }
  }

  return [error.message];
}

export type ApiFetchOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_PROXY_BASE_URL}${normalizedPath}`, {
    ...options,
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const payload = await parseResponse(response);

  if (!response.ok) {
    throw new ApiError(
      errorMessage(payload, response.status),
      response.status,
      payload,
    );
  }
  return payload as T;
}

async function parseResponse(response: Response): Promise<unknown> {
  if (response.status === 204) {
    return undefined;
  }
  const contentType = response.headers.get("content-type") ?? "";
  return contentType.includes("application/json")
    ? response.json()
    : response.text();
}

function errorMessage(payload: unknown, status: number): string {
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string") {
      return detail;
    }
  }
  return `API request failed with status ${status}`;
}
