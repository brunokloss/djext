// Where the Django backend runs. Shared by the Next proxy and the API client.
export const backendUrl = process.env.BACKEND_URL ?? "http://localhost:8000";
