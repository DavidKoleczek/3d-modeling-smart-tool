/** The app's name, as its windows, titles, and wordmark show it; the tool and its server keep their own. */
export const APP_NAME = "3D Modeling Smart Tool";

/** What the server filled into the view's meta tag `name`; nothing when it was served without one. */
function served(name: string): string | null {
  const content = document
    .querySelector<HTMLMetaElement>(`meta[name="${name}"]`)
    ?.content.trim();
  return content && !content.startsWith("{{") ? content : null;
}

/** The tool's version. */
export const VERSION = served("modeling-3d-version");

/** The tool's repository, where its docs are. */
export const DOCUMENTATION = served("modeling-3d-repository");
