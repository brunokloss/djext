// The Django admin's address, opened directly on Django (the frontend doesn't
// proxy it). Empty: no Admin link in the sidebar.
export const adminUrl = process.env.DJANGO_ADMIN_URL ?? "";
