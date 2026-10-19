# Isolated collection browser

See [browser recovery and deployment](../docs/reference/collection.md#optional-browser).
This optional service renders collection targets independently of API clients.

For a local macOS development run, install dependencies and Chromium:

```sh
npm --prefix browser ci
cd browser
npx playwright install chromium
cd ..
```

Use a private random token of at least 32 characters in both service and backend
environments. Never put this token in a browser bundle or public settings. Start the
DNS-pinned proxy in one terminal:

```sh
PYTHONPATH=. .venv/bin/python browser/public_proxy.py
```

Start the renderer in a second terminal, with the secret already exported:

```sh
export BROWSER_PROXY_URL=http://127.0.0.1:8899
node browser/service.cjs
```

Start the backend with its existing environment plus
`COLLECTION_BROWSER_URL=http://127.0.0.1:8002` and the same
`COLLECTION_BROWSER_TOKEN`. The API uses port 8001, the renderer uses 8002 and
its outgoing HTTPS proxy uses 8899. Independent API clients communicate only
with the API.

On macOS, the renderer child runs under an outer `sandbox-exec` policy denying
home-directory access except its code, dependency and Chromium directories, and
allowing network connections only to the local proxy. Native Chromium sandboxing
is disabled only for this macOS child because nested sandbox initialization is
refused; production Linux keeps Chromium's sandbox active. On other platforms,
use the supplied isolated container. The service refuses a bare Linux startup
without the container's isolation marker.

`npm --prefix browser test` checks authentication, initial-host restrictions and
lease expiry. `BROWSER_DEBUG=1` enables temporary worker debugging; it is off by
default and is not intended for production. `/health` reports service liveness,
not proof that a target repository can be reached.

The checked-in seccomp JSON comes from
[Microsoft Playwright's profile](https://github.com/microsoft/playwright/blob/main/utils/docker/seccomp_profile.json),
with the Chromium user-namespace `chroot` permission documented in the main
collection guide. Playwright and its Docker image are pinned to 1.63.0 together.
