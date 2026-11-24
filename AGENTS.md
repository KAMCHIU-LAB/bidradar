# Repository guidance

## GitHub operations on this Mac

This machine may require the local system proxy to reach GitHub. A direct `git fetch`, `git ls-remote`, or `git push` failure such as `Could not resolve host: github.com` does not by itself mean GitHub is unavailable.

Before reporting a push blocker:

1. Check `/usr/sbin/scutil --proxy` for `HTTPSEnable`, `HTTPSProxy`, and `HTTPSPort`.
2. If HTTPS proxying is enabled, retry Git with that proxy explicitly, for example:

   ```sh
   git -c http.proxy=http://127.0.0.1:7897 ls-remote origin refs/heads/main
   git -c http.proxy=http://127.0.0.1:7897 push origin main
   ```

   Use the proxy host and port reported by `scutil` rather than assuming these example values.
3. After pushing, verify the remote branch SHA with `git ls-remote` through the same proxy and compare it with `git rev-parse HEAD`.

Keep the proxy setting command-scoped; do not persist it in Git config. Never print proxy credentials or unrelated environment variables. Treat a GitHub connector read permission or repository metadata `push` permission as insufficient evidence that its Git object write API is allowed; prefer normal Git through the configured system proxy.
