import { z } from "zod";

const serverEnvironmentSchema = z.object({
  BACKEND_API_URL: z.url(),
});

export function getBackendApiUrl(): URL {
  const environment = serverEnvironmentSchema.parse(process.env);
  return new URL(environment.BACKEND_API_URL);
}
