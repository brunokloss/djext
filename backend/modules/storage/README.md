# Storage

Uploaded files (email attachments, for now) go to `backend/media/` until you set `STORAGE_URL=s3://bucket` (`backend/.env`, see `backend/modules/storage/storages.py`). The bucket stays private: every file URL is signed, expires in 5 minutes and points at the bucket itself, so the browser downloads straight from it (never through Next or Django) and the CSP allows `STORAGE_BUCKET_URL` (`frontend/.env`). Give the bucket CORS rules (`GET`, `PUT` and `POST`) for the site's origin.

On S3, every form with a file field (the admin's included) uploads straight from the browser to the bucket ([django-s3file](https://github.com/codingjoe/django-s3file)): the form sends Django only the file's key, and Django copies it to its final name inside S3. File bytes never go through Django, so it can run on AWS Lambda or Vercel. Uploads wait in `tmp/s3file/` until the form is saved; give the bucket a rule that expires that folder (a day is plenty) for forms that never are.

To try it locally, `make storage` starts RustFS, a small S3-compatible server, at http://localhost:9000 with a `djext` bucket, its CORS rules and the `tmp/s3file/` expiry (`make dev` starts it when `STORAGE_URL` points at it); the values for both `.env` files are in their `.env.example`.

## Depends on

The packages `django-storages[s3]` and `django-s3file`.
