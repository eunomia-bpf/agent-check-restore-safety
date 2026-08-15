# Restate food-ordering harness

This harness builds and runs the complete Restate `food-ordering` example from
the fixed upstream `v1.7.7` commit. It retains the six-service application,
restaurant POS, Kafka driver updates, Jaeger, and WebUI, and adds this
repository's control and non-idempotent payment services.

The build creates two source-isolated workers:

- v1 routes payment through the control API;
- v2 is byte-identical to v1 except that the payment `ctx.run` and its
  rejection branch are absent. The preceding `const token =
  ctx.rand.uuidv4()` call remains in place.

`build.sh` verifies that exact source relation before building. It also checks
the upstream archive hash, resolves one dependency lock for both workers with
the pinned Node image, retains the upstream MIT license, and writes the final
content-addressed image IDs and source hashes to an environment file. The app
and WebUI lockfiles and upstream license are retained beside that file in an
`*-evidence` directory; they are build inputs, not disposable temporary data.

The upstream WebUI Dockerfile names Node 14.17.3 but supplies no lockfile. Its
currently resolved ESLint dependency chain requires `node:path`, which makes
that image fail to compile. The harness therefore generates the WebUI lock and
runs it with the same pinned Node 22 digest as the official order app. No WebUI
source is changed; the retained lock and image ID make this necessary build
deviation explicit and repeatable.

```sh
runtime/deploy/restate/build.sh /tmp/restate-build.env
HARNESS_BUILD_ENV=/tmp/restate-build.env runtime/deploy/restate/run.sh
```

`run.sh` performs a real Compose smoke test and leaves a host evidence
directory whose path is printed at exit. Set `KEEP_HARNESS=1` to leave the
containers and volumes running for inspection. All published ports bind only
to `127.0.0.1`; the workers and payment provider share no Docker network, so a
worker can reach the provider only through control. Workers mount only the
dedicated operation-token volume: the admin token and History remain confined
to the control-state volume.

The v2 worker belongs to the `target` Compose profile and is absent from the
initial deployment. `run.sh` starts it only after the v2 Certificate has been
compiled and activated, then waits for health before registration. The
restaurant POS uses a separate image built only from `src/restaurant/server.ts`;
it does not retain or execute either order-workflow variant.

The stronger H1 preflight injects a response loss after the non-idempotent
payment provider has synced its commit:

```sh
SKIP_BUILD=1 HARNESS_BUILD_ENV=/tmp/restate-build.env \
  runtime/deploy/restate/run-h1-preflight.sh
```

It pauses the v1 invocation at its incomplete payment Run, removes v1,
recovers the unknown Operation by querying the durable payment fact, activates
v2 before starting or registering it, then kills and purges the old Restate
invocation. It re-enters v2 with the same workflow key and the exact same order
input, and requires that new generation to reach `DELIVERED` without another
payment delivery. A separate non-idempotent provider receives the same naive
request twice and must commit twice; this rules out provider idempotency as the
explanation for the protected provider's one delivery and one commit. The
script retains raw `/query` rows, binary History and head files, provider
records, deployments, container evidence, and a summary. It is a focused H1
preflight, not the complete H0/H1 manifest consumed by `check.py`.

The upstream source is MIT licensed:
<https://github.com/restatedev/examples/tree/2d429daae784d20982691fb31431702b4ad30a6b/typescript/end-to-end-applications/food-ordering>.
The upstream WebUI retains its attribution to the MIT-licensed
`jeffersonRibeiro/react-shopping-cart` project.
