# Storage Guide

Octopus stores asset content through a storage provider and records metadata in
the `assets` table. Business APIs keep returning the same content URL:

```text
GET /api/assets/{assetId}/content
```

This route checks organization access, reads the object from the configured
provider, and returns the stored bytes with the asset content type and filename.

## Providers

### Local Disk

Local disk is the default provider.

```powershell
$env:OCTOPUS_STORAGE_PROVIDER = "local_disk"
$env:OCTOPUS_STORAGE_DIR = ".octopus/instances/default/data/storage"
```

If `OCTOPUS_STORAGE_PROVIDER` is unset, Octopus uses `local_disk`.

Objects are written under:

```text
.octopus/instances/default/data/storage/<orgId>/<namespace>/<yyyy>/<mm>/<dd>/<uuid>-<filename>
```

### MinIO

MinIO uses the S3-compatible provider.

```powershell
$env:OCTOPUS_STORAGE_PROVIDER = "minio"
$env:OCTOPUS_STORAGE_ENDPOINT = "http://127.0.0.1:9000"
$env:OCTOPUS_STORAGE_BUCKET = "octopus"
$env:OCTOPUS_STORAGE_ACCESS_KEY = "minioadmin"
$env:OCTOPUS_STORAGE_SECRET_KEY = "minioadmin"
$env:OCTOPUS_STORAGE_REGION = "us-east-1"
$env:OCTOPUS_STORAGE_FORCE_PATH_STYLE = "1"
```

The bucket must already exist. The provider writes objects with the same object
key shape used by local disk:

```text
<orgId>/<namespace>/<yyyy>/<mm>/<dd>/<uuid>-<filename>
```

For MinIO, path-style addressing is normally required, so
`OCTOPUS_STORAGE_FORCE_PATH_STYLE=1` is the recommended setting.

### S3-Compatible

The same provider can be used for another S3-compatible service:

```powershell
$env:OCTOPUS_STORAGE_PROVIDER = "s3"
$env:OCTOPUS_STORAGE_ENDPOINT = "https://s3.example.com"
$env:OCTOPUS_STORAGE_BUCKET = "octopus"
$env:OCTOPUS_STORAGE_ACCESS_KEY = "<access-key>"
$env:OCTOPUS_STORAGE_SECRET_KEY = "<secret-key>"
$env:OCTOPUS_STORAGE_REGION = "us-east-1"
$env:OCTOPUS_STORAGE_FORCE_PATH_STYLE = "0"
```

## What Gets Stored

These paths create assets:

- Chat attachment multipart uploads.
- Issue attachment multipart uploads.
- Runtime work products that include inline `content`.

Each asset records:

```text
provider
object_key
content_type
byte_size
sha256
original_filename
```

## Current Boundaries

- One server process uses one configured provider at a time.
- Existing asset rows still depend on the provider that can read their
  `object_key`.
- The first MinIO implementation proxies downloads through the server. It does
  not issue signed URLs.
- Bucket auto-creation, CDN, multipart upload, and cross-provider migration are
  not implemented.
