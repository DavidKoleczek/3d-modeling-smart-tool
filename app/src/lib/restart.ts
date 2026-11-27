/**
 * What the view tells the page around it when the server is about to end and come back, so that page loads again once
 * it has. Another host makes nothing of it.
 */
export const SERVER_RESTARTING = "modeling-3d/server-restarting";

// Whether the server is one that comes back by itself, which is so when the Windows app runs it.
let restarts = false;

export function tellHostOfRestart() {
  window.parent.postMessage({ type: SERVER_RESTARTING }, "*");
}

/** Says the server is one that comes back when it ends, as it does when the Windows app updates it from its own menu. */
export function expectRestarts() {
  restarts = true;
}

/** A call got no answer at all. From a server that comes back, that is a restart nobody told the view of. */
export function gotNoAnswer() {
  if (restarts) {
    tellHostOfRestart();
  }
}
