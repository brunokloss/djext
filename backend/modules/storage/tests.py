from unittest.mock import MagicMock

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.test import SimpleTestCase, override_settings

from modules.storage.storages import DirectS3Storage, storages_from_url


class StoragesFromUrlTest(SimpleTestCase):
    def test_empty_is_the_disk(self):
        default = storages_from_url("")["default"]
        self.assertIn("FileSystemStorage", default["BACKEND"])
        self.assertNotIn("OPTIONS", default)

    def test_the_disk_follows_media_root(self):
        # A fixed `location` would ignore this, and the tests would leave
        # their files in backend/media.
        with override_settings(MEDIA_ROOT="/tmp/elsewhere"):
            self.assertEqual(default_storage.location, "/tmp/elsewhere")

    def test_tests_use_the_disk(self):
        self.assertNotIsInstance(default_storage, DirectS3Storage)

    def test_aws_bucket_without_keys(self):
        default = storages_from_url(
            "s3://my-bucket?region_name=sa-east-1&location=bruno"
        )["default"]
        self.assertEqual(default["BACKEND"], "modules.storage.storages.DirectS3Storage")
        options = default["OPTIONS"]
        self.assertEqual(options["bucket_name"], "my-bucket")
        self.assertEqual(options["region_name"], "sa-east-1")
        self.assertEqual(options["location"], "bruno")
        self.assertFalse(options["file_overwrite"])
        self.assertNotIn("access_key", options)

    def test_keys_and_endpoint(self):
        options = storages_from_url(
            "s3://key:s%40cret@files?endpoint_url=http://localhost:9000"
            "&querystring_expire=60",
        )["default"]["OPTIONS"]
        self.assertEqual(options["access_key"], "key")
        self.assertEqual(options["secret_key"], "s@cret")
        self.assertEqual(options["endpoint_url"], "http://localhost:9000")
        self.assertEqual(options["querystring_expire"], 60)

    def test_bad_url(self):
        with self.assertRaises(ValueError):
            storages_from_url("ftp://files")


class DirectS3StorageUrlTest(SimpleTestCase):
    def test_url_is_the_bucket_signed(self):
        storage = DirectS3Storage(
            bucket_name="files",
            access_key="key",
            secret_key="secret",
            endpoint_url="http://localhost:9000",
            region_name="us-east-1",
            signature_version="s3v4",
        )
        url = storage.url("emails/report final.pdf")
        self.assertTrue(
            url.startswith("http://localhost:9000/files/emails/report%20final.pdf?")
        )
        self.assertIn("X-Amz-Signature=", url)


S3 = {
    "default": {
        "BACKEND": "modules.storage.storages.DirectS3Storage",
        "OPTIONS": {
            "bucket_name": "files",
            "access_key": "key",
            "secret_key": "secret",
            "endpoint_url": "http://localhost:9000",
            "region_name": "us-east-1",
        },
    },
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def bucket_storage():
    storage = DirectS3Storage(**S3["default"]["OPTIONS"])
    storage._bucket = MagicMock(name="bucket")
    storage._bucket.name = "files"
    return storage


class DirectS3StorageSaveTest(SimpleTestCase):
    def test_a_file_already_in_the_bucket_is_copied_there(self):
        storage = bucket_storage()
        uploaded = MagicMock(_storage=storage, content_type=None)
        uploaded.obj.key = "tmp/s3file/abc/报告.pdf"
        name = storage._save("attachments/报告.pdf", uploaded)
        self.assertEqual(name, "attachments/报告.pdf")
        storage.bucket.Object.assert_called_once_with("attachments/报告.pdf")
        (source,) = storage.bucket.Object.return_value.copy.call_args.args
        self.assertEqual(source, {"Bucket": "files", "Key": "tmp/s3file/abc/报告.pdf"})
        extra = storage.bucket.Object.return_value.copy.call_args.kwargs["ExtraArgs"]
        self.assertEqual(extra["ContentType"], "application/pdf")
        uploaded.obj.delete.assert_called_once_with()
        storage.bucket.Object.return_value.upload_fileobj.assert_not_called()

    def test_any_other_file_is_uploaded(self):
        storage = bucket_storage()
        storage._save("attachments/a.txt", ContentFile(b"hi", name="a.txt"))
        storage.bucket.Object.return_value.upload_fileobj.assert_called_once()
        storage.bucket.Object.return_value.copy.assert_not_called()
