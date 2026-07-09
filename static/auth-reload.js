// Re-authenticate when the oauth2-proxy session expires mid-session: the SPA's fetch to /amiss/api/*
// gets a cross-origin 302 to the IdP that fetch() can't follow (CORS -> "request error"); a full-page
// reload lets the browser follow that redirect and re-login.
(function () {
  const original = window.fetch;
  const GUARD_MS = 15000;
  function reauth() {
    const now = Date.now();
    const last = parseInt(sessionStorage.getItem("amiss:reauth-at") || "0", 10);
    if (now - last < GUARD_MS) return false; // avoid reload loops on a genuine outage
    sessionStorage.setItem("amiss:reauth-at", String(now));
    window.location.reload();
    return true;
  }
  function sameOrigin(input) {
    const url = typeof input === "string" ? input : (input && input.url) || "";
    return url.startsWith("/") || url.startsWith(window.location.origin);
  }
  window.fetch = function (input, init) {
    return original(input, init)
      .then(function (response) {
        if (response.status === 401 && sameOrigin(input)) reauth();
        return response;
      })
      .catch(function (error) {
        // The expired-session cross-origin redirect fails as a TypeError ("Failed to fetch").
        // Only that triggers re-auth -- NOT an AbortError (in-flight request cancelled on navigation)
        // or any other rejection, which must propagate unchanged.
        if (sameOrigin(input) && error instanceof TypeError && reauth()) {
          return new Promise(function () {}); // pending; page is reloading
        }
        throw error;
      });
  };
})();
