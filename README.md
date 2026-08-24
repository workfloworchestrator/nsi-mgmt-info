# nsi-mgmt-info

The NSI Management Information Service (AMISS) offers an interface to obtain information that ANA management 
needs for decision making. In other words, this service makes available and visualizes data effectively to enable strategic and engineering decision-making processes. The nsi-mgmt-info service uses information from the NSI-Orchestrator and other ANA-NSI 
components to generate useful overviews and statistics.
  
## Project ANA-GRAM

This software is being developed by the 
[Advanced North-Atlantic Consortium](https://www.anaeng.global/), 
a cooperation between National Education and Research Networks (NRENs) and 
research partners to provide network connectivity for research and education 
across the North-Atlantic, as part of the ANA-GRAM project. 

The goal of the ANA-GRAM project is to federate the ANA trans-Atlantic links through
[Network Service Interface (NSI)](https://ogf.org/documents/GFD.237.pdf)-based automation.
This will enable the automated provisioning of L2 circuits spanning different domains 
between research parties on other sides of the Atlantic. The ANA-GRAM project is 
spearheaded by the ANA Platform & Requirements Working Group, under guidance of the 
ANA Engineering and ANA Planning Groups.  

<p align="center" width="50%">
    <img width="50%" src="/artwork/ana-logo-scaled-ab2.png">
</p>

## Architecture

The diagram below shows the ANA-GRAM automation stack and how AMISS fits into the broader architecture.

<p align="center">
    <img src="/artwork/ana-automation-stack.drawio.svg">
</p>

**Color legend:**

| Color | Meaning |
|-------|---------|
| Purple | Existing software deployed in every participating network |
| Green | Existing NSI infrastructure software |
| Orange | Software developed as part of ANA-GRAM |

**Components:**

- [**AMISS**](https://github.com/workfloworchestrator/nsi-mgmt-info) (this repository) — The NSI Management Information Service, a read-only management portal giving an overview of the services configured on the ANA infrastructure and their operational status. It queries the NSI Orchestrator as its source of truth, the DDS Proxy to reconcile the known topology against it, and the NSI Aggregator Proxy for multi-domain circuit paths.
- [**NSI Orchestrator**](https://github.com/workfloworchestrator/nsi-orchestrator) — Central orchestration layer that manages the lifecycle of topologies, switching services, STPs, SDPs, and multi-domain connections. It uses the DDS Proxy for topology visibility and the NSI Aggregator Proxy as its Network Resource Manager.
- [**DDS Proxy**](https://github.com/workfloworchestrator/nsi-dds-proxy) — Fetches NML topology documents from the upstream DDS, parses them, and exposes the data as a JSON REST API.
- [**NSI Aggregator Proxy**](https://github.com/workfloworchestrator/nsi-aggregator-proxy) — Translates simple REST/JSON calls into NSI Connection Service v2 SOAP messages toward the NSI Aggregator, abstracting NSI protocol complexity behind a linear state machine.
- [**DDS**](https://github.com/BandwidthOnDemand/nsi-dds) — The NSI Document Distribution Service, a distributed registry where networks publish and discover NML topology documents and NSA descriptions.
- [**PCE**](https://github.com/BandwidthOnDemand/nsi-pce) — The NSI Path Computation Element, which computes end-to-end paths across multiple network domains using topology information from the DDS.
- [**NSI Aggregator (Safnari)**](https://github.com/BandwidthOnDemand/nsi-safnari) — An NSI Connection Service v2.1 Aggregator that coordinates connection requests across multiple provider domains, using the PCE for path computation.
- [**SuPA**](https://github.com/workfloworchestrator/SuPA) — The SURF ultimate Provider Agent, an NSI Provider Agent that manages circuit reservation, creation, and removal within a single network domain. Uses gRPC instead of SOAP, and is always deployed together with [**PolyNSI**](https://github.com/workfloworchestrator/PolyNSI), a bidirectional SOAP-to-gRPC translation proxy.

## What AMISS shows

AMISS is **read-only**: it surfaces and visualizes information sourced live from the ANA-NSI stack and does not create or modify anything (there is no NSI control plane behind it). The **WFO orchestrator** is the source of truth; the **DDS proxy** is used to reconcile the known topology against it. Every page fetches on demand — there is no database or cache.

- **Dashboard** (landing page): a summary card per area with at-a-glance counts — circuits by state, and STPs/SDPs by reconciliation status — each card linking to its full table.
- **Circuits** (`/circuits`): the MDP2P point-to-point circuits from the WFO — source/destination STP and VLAN, bandwidth, NSI state, and **who created the circuit** (from the create workflow, name only to keep the column narrow); the detail view also shows the creator's email alongside the name, the connection and global-reservation ids, plus the circuit's multi-domain **path** (the aggregator's per-segment provider-NSA, STPs, capacity, and status). Tabbed by state (**Activated / Failed / Terminated / All**), sortable, with a per-circuit detail page.
- **Service Termination Points** (`/stp`): the STP subscriptions held by the WFO, reconciled against the DDS topology and flagged **backed by DDS** (in both), **DDS only** (topology present but no subscription yet), or **not in DDS** (a subscription the DDS no longer advertises). The table shows the port's VLAN range and capacity, with the topology prefix split off the STP id into its own **Network** column so the ids stay readable. Tabbed by reconciliation status (**All / Backed by DDS / Not in DDS / DDS only**), sortable, with a per-STP detail page that lists the **circuits currently using that port** — the "what is using this, can I decommission it?" view. Terminated circuits are left out there, and the match is on the endpoint's STP *id*: the circuits table shows each endpoint by name, which is display text and joins to nothing.
- **Service Demarcation Points** (`/sdp`): the same WFO-vs-DDS reconciliation, tabs and detail page for the demarcation points that pair two STPs. Both ends are shown by **name** (falling back to the STP id where the WFO has none) — the ids are long, near-identical down the column, and kept on the detail page. An SDP's VLAN range and capacity come from its two member STPs: one value when the ends agree, and **both** when they do not, since the ends of one inter-domain link should match and a mismatch is a defect this page exists to surface (capacity stays the lower of the two, which is what the link can carry). The detail page lists the circuits crossing the SDP.
- **Spectrum** (`/spectrum`): the **SDPs** (each the inter-domain link between two topologies) and the circuits crossing each, showing per-SDP circuit count, the link's own capacity, the capacity **reserved** on it and the resulting **utilisation**. The SDP inventory comes from the WFO SDP subscriptions; the paths come from the **aggregator proxy** (`GET /reservations?detail=full`), the only source of a circuit's multi-domain segments. Only circuits with a **non-terminated WFO subscription** are shown (matched by connection id), so `/spectrum` stays consistent with `/circuits`; each circuit's details (description, bandwidth, state) come from the **WFO** — only the per-SDP VLAN comes from the aggregator path. Each row links to its SDP page for the circuit list; multi-domain circuits matching no known SDP have no SDP to link to and are listed inline under **Unattributed circuits**.
- **Health** (`/healthcheck`): a liveness/readiness probe returning JSON.

## Performance

Every page fetches live per request (no cache). A page's accessor issues one or more upstream calls —
WFO GraphQL, DDS proxy, aggregator proxy — and independent calls run **concurrently**, so a page's
wall-clock is roughly the *slowest single upstream*, not the sum. The dashboard composes all its cards
from one concurrent fetch per upstream (each fetched once), so it is about as fast as the slowest one.

The dominant cost is a **fixed ~400–500 ms per WFO GraphQL request**, largely independent of the query
or result size (responses are a few KB and JSON parsing is negligible). That points at per-request work
at the orchestrator — most likely **OIDC token validation on every request** (the forwarded access
token is introspected/validated at the WFO) plus GraphQL/DB setup — so a single WFO round-trip is the
practical per-page floor. Set `LOG_LEVEL=DEBUG` to see per-request `elapsed_ms` timings.

Directions to improve, largest first:

- **Orchestrator-side (biggest win):** cache token introspection / validation at the WFO so each
  GraphQL request no longer pays the full auth cost. This speeds up **every** page across the stack and
  is the only way under the one-round-trip floor. Out of scope for this repo.
- **Batch the dashboard's WFO queries:** issue the circuits/STP/SDP subscription queries as a single
  aliased GraphQL request instead of three, trading three WFO round-trips for one (also helps
  `/spectrum`, which makes two). Cannot beat the single-round-trip floor.
- A response cache would hide the latency but adds staleness; the orchestrator is the source of truth,
  so the token-validation fix above is preferred.

## Prerequisites

- **Standard deployment — behind the ANA portal (recommended).** The portal's oauth2-proxy authenticates the user via OIDC, enforces group membership, and forwards the user's identity and access token (`X-Auth-Request-*`). AMISS forwards that token to the WFO orchestrator on each request, so access is authorised **end-to-end, per user**, and **no client certificate is required**.
- **Standalone / direct to the ANA-NSI proxies (alternative).** To reach the DDS (and aggregator) proxies without the portal, AMISS authenticates with either mutual TLS (`NSI_PROXY_MTLS_ENABLED=True` plus a client certificate and key) or edge-identity headers (`NSI_PROXY_MTLS_ENABLED=False`) — for local development or when mTLS is terminated at the ingress.
- Python 3.13+ (for running from source) or Docker.

## Configuration

All settings can be configured via environment variables or an `amiss.env` file placed in the working directory. Environment variables take precedence over the env file.

| Variable | Default | Description |
|---|---|---|
| `NSI_AMISS_WFO_URL` | `http://orchestrator.domain.example` | Base URL of the **WFO orchestrator** — primary source of circuits and STP/SDP subscriptions. The GraphQL client appends `/api/graphql` and forwards the end-user's OIDC token per request. |
| `NSI_DDS_PROXY_URL` | `http://dds.domain.example/dds/` | Base URL of the **nsi-dds-proxy** — topology (STPs/SDPs) that the `/stp` and `/sdp` views reconcile against the WFO subscriptions. |
| `NSI_AGG_PROXY_URL` | `http://aggregator-proxy.domain.example/` | Base URL of the **nsi-aggregator-proxy** — source of circuit path segments for the `/spectrum` view (fetched with AMISS's proxy identity, like the DDS proxy). |
| `NSI_PROXY_MTLS_ENABLED` | `True` | How AMISS authenticates to the proxies. `True` = mutual TLS with the client cert/key below. `False` = send edge-identity headers (`X-Auth-Method`/`X-Client-DN`) instead — for local dev or in-cluster calls where mTLS is terminated at the ingress. |
| `NSI_PROXY_AUTH_METHOD` | `x509` | Value sent in the `X-Auth-Method` header when `NSI_PROXY_MTLS_ENABLED=False`. |
| `NSI_PROXY_CLIENT_DN` | `CN=claude@local.laptop` | Client DN sent in the `X-Client-DN` header when `NSI_PROXY_MTLS_ENABLED=False`. Must be authorized by the proxies. |
| `NSI_AMISS_CERTIFICATE` | _(unset)_ | Path to the PEM client certificate for mutual TLS. Required only when `NSI_PROXY_MTLS_ENABLED=True`. |
| `NSI_AMISS_PRIVATE_KEY` | _(unset)_ | Path to the PEM private key for the client certificate. Required only when `NSI_PROXY_MTLS_ENABLED=True`. |
| `CA_CERTIFICATES` | _(unset)_ | Path to a PEM file or a `c_rehash` directory of CA certificates used to verify the proxies. When unset, the default requests CA bundle is used. |
| `VERIFY_REQUESTS` | `True` | Verify TLS certificates on outbound requests. Only disable for debugging. |
| `NSI_AMISS_HOST` | `127.0.0.1` | Interface the server binds to. The container image sets this to `0.0.0.0`. |
| `NSI_AMISS_PORT` | `8000` | TCP port the server listens on. The container image sets this to `8080`. |
| `STATIC_DIRECTORY` | `static` | Directory containing static assets (images). |
| `SITE_TITLE` | `AMISS` | Title shown in the web UI. |
| `ROOT_PATH` | _(empty)_ | ASGI root-path prefix when deployed behind a reverse proxy that strips a path prefix. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. Accepted values: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |

A ready-to-use template is provided in `amiss.env`. The application automatically reads this file from the working directory when it starts, so in most cases you only need to edit it in place.

If you want to maintain multiple configurations (e.g. for different environments), copy it and pass the copy explicitly via `docker run --env-file` or by exporting the variables in your shell:

```bash
cp amiss.env production.env
# edit production.env

# Use with Docker:
docker run --env-file production.env ...

# Use in your shell (exports all non-comment lines as environment variables):
export $(grep -v '^#' production.env | xargs)
nsi-mgmt-info
```

Note that `docker run --env-file` expects plain `KEY=VALUE` lines — no `export` keyword, no quotes around values. The provided `amiss.env` is already in this format.

## Running the Application

> **Note on authentication.** The WFO-backed views (circuits, STP/SDP, dashboard) authorise
> **per user**: AMISS forwards the caller's OIDC access token (`X-Auth-Request-Access-Token`, or a
> plain `Authorization: Bearer`) to the orchestrator. In the standard ANA deployment the portal's
> oauth2-proxy supplies that token and **no client certificate is needed**. The examples below run
> AMISS **standalone** and show mutual-TLS auth to the DDS/aggregator proxies; a standalone run must
> still arrange the WFO token itself, and can set `NSI_PROXY_MTLS_ENABLED=False` to use edge-identity
> headers for the proxies instead of certificates.

### From source with uv

Install dependencies and start the server:

```bash
uv sync
nsi-mgmt-info
```

The `nsi-mgmt-info` entry point starts a Uvicorn server using the host and port from your configuration. Make sure `amiss.env` is present in the directory you run the command from, or export the required environment variables beforehand.

### With Python directly

If you have the package installed in your Python environment:

```bash
pip install .
nsi-mgmt-info
```

Or invoke Uvicorn manually, which lets you override host, port, and the number of workers:

```bash
uvicorn amiss:app --host 0.0.0.0 --port 8000 --workers 4
```

Note that when using `uvicorn` directly, `NSI_AMISS_HOST` and `NSI_AMISS_PORT` are ignored — pass them as CLI arguments instead.

### With Docker

A pre-built image is available on the GitHub Container Registry:

```
ghcr.io/workfloworchestrator/nsi-mgmt-info:latest
```

Run it directly, mounting your certificate files and passing configuration via environment variables:

```bash
docker run --rm \
  -p 8080:8080 \
  -v /path/to/your/certs:/certs:ro \
  -e NSI_AMISS_CERTIFICATE=/certs/client-certificate.pem \
  -e NSI_AMISS_PRIVATE_KEY=/certs/client-private-key.pem \
  -e CA_CERTIFICATES=/certs/ca-bundle.pem \
  -e NSI_DDS_PROXY_URL=https://your-dds-proxy/dds/ \
  -e NSI_AGG_PROXY_URL=https://your-aggregator-proxy/ \
  -e NSI_AMISS_WFO_URL=https://your-orchestrator-server \
  ghcr.io/workfloworchestrator/nsi-mgmt-info:latest
```

Or pass all settings via an env file:

```bash
docker run --rm \
  -p 8080:8080 \
  -v /path/to/your/certs:/certs:ro \
  --env-file production.env \
  ghcr.io/workfloworchestrator/nsi-mgmt-info:latest
```

If you prefer to build the image yourself, pass the version to stamp into the package (see
[Versioning](#versioning)):

```bash
docker build --build-arg VERSION="$(uvx --from setuptools-scm python -m setuptools_scm)" -t nsi-mgmt-info .
```

## Versioning

The release git tag is the only place a version is written by hand. `pyproject.toml` declares
`dynamic = ["version"]` and setuptools-scm derives it: a tag builds `0.1.1`, any other commit builds
the next patch as a dev release with its commit, `0.1.2.dev3+g1a2b3c4`. AMISS logs that version at
startup and exposes it via `importlib.metadata.version("nsi-mgmt-info")`.

The container build has no `.git`, so `.github/workflows/container.yml` checks out with
`fetch-depth: 0`, resolves the version on the runner, and passes it as `--build-arg VERSION=...`,
which the `Dockerfile` hands to setuptools-scm as `SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NSI_MGMT_INFO`.
A build without that argument fails rather than producing a mislabelled image.

### On Kubernetes

Store your client certificate and key in a Secret, then reference them in a Deployment:

```bash
kubectl create secret generic mgmt-info-certs \
  --from-file=client-certificate.pem=/path/to/client-certificate.pem \
  --from-file=client-private-key.pem=/path/to/client-private-key.pem \
  --from-file=ca-bundle.pem=/path/to/ca-bundle.pem
```

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: nsi-mgmt-info
spec:
  replicas: 1
  selector:
    matchLabels:
      app: nsi-mgmt-info
  template:
    metadata:
      labels:
        app: nsi-mgmt-info
    spec:
      containers:
        - name: nsi-mgmt-info
          image: ghcr.io/workfloworchestrator/nsi-mgmt-info:latest
          ports:
            - containerPort: 8080
          env:
            - name: NSI_DDS_PROXY_URL
              value: "https://your-dds-proxy/dds/"
            - name: NSI_AGG_PROXY_URL
              value: "https://your-aggregator-proxy/"
            - name: NSI_AMISS_WFO_URL
              value: "https://your-wfo-server"
            - name: NSI_AMISS_CERTIFICATE
              value: "/certs/client-certificate.pem"
            - name: NSI_AMISS_PRIVATE_KEY
              value: "/certs/client-private-key.pem"
            - name: CA_CERTIFICATES
              value: "/certs/ca-bundle.pem"
          volumeMounts:
            - name: certs
              mountPath: /certs
              readOnly: true
      volumes:
        - name: certs
          secret:
            secretName: mgmt-info-certs
---
apiVersion: v1
kind: Service
metadata:
  name: nsi-mgmt-info
spec:
  selector:
    app: nsi-mgmt-info
  ports:
    - port: 80
      targetPort: 8080
```

### With Helm chart

Using the same secret as above, and the `values.yaml` as below, add an `ingress` if needed,
and install with:

```shell
helm upgrade --install --namespace development --values values.yaml nsi-mgmt-info chart
```

```yaml
image:
  pullPolicy: IfNotPresent
  repository: ghcr.io/workfloworchestrator/nsi-mgmt-info
  tag: latest
env:
  NSI_DDS_PROXY_URL: https://nsi-dds-proxy.your.domain/dds/
  NSI_AGG_PROXY_URL: https://nsi-aggregator-proxy.your.domain/
  NSI_AMISS_WFO_URL: https://nsi-orchestrator.your.domain
  CA_CERTIFICATES: /certs/ca-bundle.pem
  NSI_AMISS_CERTIFICATE: /certs/client-certificate.pem
  NSI_AMISS_PRIVATE_KEY: /certs/client-private-key.pem
  LOG_LEVEL: INFO
livenessProbe:
  httpGet:
    path: /healthcheck
    port: 8080
readinessProbe:
  httpGet:
    path: /healthcheck
    port: 8080
resources:
  limits:
    cpu: 1000m
    memory: 128Mi
  requests:
    cpu: 10m
    memory: 64Mi
volumeMounts:
  - mountPath: /certs
    name: certs
    readOnly: true
volumes:
  - name: certs
    secret:
      optional: false
      secretName: mgmt-info-certs
```

