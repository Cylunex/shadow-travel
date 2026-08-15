export type CurrentUser = {
  shadow_user_id: string;
  username: string;
  display_name: string;
  email: string;
};

export const basePath = import.meta.env.BASE_URL;

export async function currentUser(signal?: AbortSignal): Promise<CurrentUser | null> {
  const response = await fetch(`${basePath}api/browser/v1/me`, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    signal
  });
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Travel API returned HTTP ${response.status}`);
  }
  return (await response.json()) as CurrentUser;
}

export function login(): void {
  const returnTo = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const target = `${basePath}auth/login?return_to=${encodeURIComponent(returnTo)}`;
  window.location.replace(target);
}
