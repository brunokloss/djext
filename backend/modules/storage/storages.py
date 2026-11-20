"""Turns STORAGE_URL into Django's `STORAGES` (where uploaded files go)."""

from urllib.parse import parse_qs, unquote, urlsplit

from storages.backends.s3 import S3Storage
from storages.utils import clean_name


class DirectS3Storage(S3Storage):
    """S3, with signed file URLs pointing at the bucket itself.

    A file the browser already uploaded to the bucket (django-s3file, see
    settings.py) is copied inside S3 to its final key, then its upload is
    deleted: its bytes never go through Django, so Django can run where request
    bodies are small (AWS Lambda, Vercel). Any other file is uploaded as usual."""

    def _save(self, name, content):
        source = getattr(getattr(content, "obj", None), "key", None)
        storage = getattr(content, "_storage", None)
        if source is None or getattr(storage, "bucket_name", None) != self.bucket_name:
            return super()._save(name, content)
        cleaned = clean_name(name)
        params = self._get_write_parameters(self._normalize_name(cleaned), content)
        target = self.bucket.Object(self._normalize_name(cleaned))
        target.copy(
            {"Bucket": self.bucket.name, "Key": source},
            ExtraArgs={**params, "MetadataDirective": "REPLACE"},
        )
        content.obj.delete()
        return cleaned


def storages_from_url(url: str) -> dict:
    """Empty: files on disk, in MEDIA_ROOT (development).

    `s3://bucket` keeps them in that S3 bucket, private: every URL is signed and
    expires in 5 minutes. Without a key in the URL, boto3 finds the credentials
    itself (AWS_PROFILE, the ECS or EC2 role, AWS_ACCESS_KEY_ID). Any other
    S3-compatible server takes its key, secret and address:
    `s3://KEY:SECRET@bucket?endpoint_url=http://localhost:9000`.

    The query sets django-storages' S3 options, e.g. `region_name=sa-east-1`,
    `location=bruno` (a folder inside the bucket) or `querystring_expire=60`.

    The browser talks to the bucket itself (downloads and uploads), so the
    frontend's CSP allows it (STORAGE_BUCKET_URL) and the bucket needs CORS for
    the site's origin.
    """
    staticfiles = {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}
    if not url:
        return {
            "default": {
                # No `location`: it follows MEDIA_ROOT, override_settings too.
                "BACKEND": "django.core.files.storage.FileSystemStorage",
            },
            "staticfiles": staticfiles,
        }
    parts = urlsplit(url)
    if parts.scheme != "s3" or not parts.hostname:
        raise ValueError("STORAGE_URL must be empty (disk) or look like s3://bucket")
    options = {
        # Two uploads with the same name get two keys, never one overwriting the other.
        "file_overwrite": False,
        "querystring_expire": 300,
        "signature_version": "s3v4",
    }
    for key, values in parse_qs(parts.query).items():
        value = values[0]
        options[key] = int(value) if value.isdigit() else value
    # urlsplit lowercases the hostname; bucket names are lowercase anyway.
    options["bucket_name"] = parts.hostname
    if parts.username:
        options["access_key"] = unquote(parts.username)
        options["secret_key"] = unquote(parts.password or "")
    return {
        "default": {
            "BACKEND": "modules.storage.storages.DirectS3Storage",
            "OPTIONS": options,
        },
        "staticfiles": staticfiles,
    }
