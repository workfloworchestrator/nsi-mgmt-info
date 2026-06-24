# nsi-mgmt-info

The NSI Management Information Service offers an interface to obtain information that ANA manangement 
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

## Prerequisites

- For mutual-TLS auth to the ANA-NSI proxies (`NSI_PROXY_MTLS_ENABLED=True`): a valid client certificate and private key. Not needed when using header auth (`NSI_PROXY_MTLS_ENABLED=False`).
- Python 3.13+ (for running from source) or Docker.

## Configuration

All settings can be configured via environment variables or an `amiss.env` file placed in the working directory. Environment variables take precedence over the env file.

| Variable | Default | Description |
|---|---|---|
| `NSI_DDS_PROXY_URL` | `http://dds.domain.example/dds/` | Base URL of the **nsi-dds-proxy** — source of topology (STPs and SDPs). |
| `NSI_AGG_PROXY_URL` | `http://aggregator-proxy.domain.example/` | Base URL of the **nsi-aggregator-proxy** — source of reservations and segments. |
| `NSI_AMISS_WFO_URL` | `http://orchestrator.domain.example/mgmt` | Base URL of the upstream Workflow Orchestrator (WFO) management API. |
| `NSI_PROXY_MTLS_ENABLED` | `True` | How AMISS authenticates to the proxies. `True` = mutual TLS with the client cert/key below. `False` = send edge-identity headers (`X-Auth-Method`/`X-Client-DN`) instead — for local dev or in-cluster calls where mTLS is terminated at the ingress. |
| `NSI_PROXY_AUTH_METHOD` | `x509` | Value sent in the `X-Auth-Method` header when `NSI_PROXY_MTLS_ENABLED=False`. |
| `NSI_PROXY_CLIENT_DN` | `CN=claude@local.laptop` | Client DN sent in the `X-Client-DN` header when `NSI_PROXY_MTLS_ENABLED=False`. Must be authorized by the proxies. |
| `NSI_AMISS_CERTIFICATE` | _(unset)_ | Path to the PEM client certificate for mutual TLS. Required only when `NSI_PROXY_MTLS_ENABLED=True`. |
| `NSI_AMISS_PRIVATE_KEY` | _(unset)_ | Path to the PEM private key for the client certificate. Required only when `NSI_PROXY_MTLS_ENABLED=True`. |
| `CA_CERTIFICATES` | _(unset)_ | Path to a PEM file or a `c_rehash` directory of CA certificates used to verify the proxies. When unset, the default requests CA bundle is used. |
| `VERIFY_REQUESTS` | `True` | Verify TLS certificates on outbound requests. Only disable for debugging. |
| `DATABASE_URI` | `sqlite:///file::memory:?cache=shared&uri=true` | SQLModel database URI. Defaults to ephemeral shared in-memory SQLite; use a file path or PostgreSQL URI to persist. |
| `SEED_DUMMY_SEGMENTS_DATA` | `False` | Seed dummy reservations/segments at startup (dev/demo only). |
| `NSI_AMISS_HOST` | `127.0.0.1` | Interface the server binds to. The container image sets this to `0.0.0.0`. |
| `NSI_AMISS_PORT` | `8000` | TCP port the server listens on. The container image sets this to `8080`. |
| `STATIC_DIRECTORY` | `static` | Directory containing static assets (images, templates). |
| `SITE_TITLE` | `AMISS` | Title shown in the web UI. |
| `ROOT_PATH` | _(empty)_ | ASGI root-path prefix when deployed behind a reverse proxy that strips a path prefix. |
| `SQL_LOGGING` | `False` | Log SQLAlchemy statements. |
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
  -e NSI_AMISS_WFO_URL=https://your-orchestrator-server/mgmt \
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

If you prefer to build the image yourself:

```bash
docker build -t nsi-mgmt-info .
```

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
              value: "https://your-wfo-server/mgmt"
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
  NSI_AMISS_WFO_URL: https://nsi-orchestrator.your.domain/mgmt
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

