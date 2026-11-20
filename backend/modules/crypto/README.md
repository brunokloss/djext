# Crypto

`modules/crypto` encrypts data with [Tink](https://developers.google.com/tink), one key per owner (any model instance: a user, a company): `encrypt(owner, data)` and `decrypt(owner, data)` for bytes, `encrypt_text` and `decrypt_text` for strings, all in `modules/crypto/crypto.py`. Each owner's key (`Keyset`, in the admin, and read only on the user's page) is made on first use and stored wrapped by the master key, `CRYPTO_KMS_URI`, so the database alone decrypts nothing:

- **Production:** an AWS KMS key, `aws-kms://arn:aws:kms:<region>:<account>:key/<id>` (credentials from boto3's usual places). The KMS is called once per owner key and process, then the key stays in memory.
- **Development and CI:** `fake-kms://...`, which holds the key itself. `make install` writes one to `backend/.env`; `manage.py crypto_fake_kms_uri` makes another. `check --deploy` refuses it with `DEBUG` off.

`aad` binds a ciphertext to where it lives (`aad=b"invoice:42:password"`): with another `aad` it won't decrypt, so it can't be copied to another row. `encrypt_envelope(payload, aad)` is for data with no owner: it uses the master key itself, a KMS call each time, and `aad` is required (the record's id), since no owner key keeps copies apart.

`shred(request, owner)` deletes an owner's key, so everything encrypted with it can never be read again, backups included (crypto-shredding, for LGPD erasure), and logs `crypto.shred`. Deleting a key in the admin shreds it, and so does anonymizing a user (`user.anonymize`). Deleting the owner doesn't: shred first. Changing `CRYPTO_KMS_URI` makes every key, and so all the data, unreadable.

## Depends on

The package `tink` and `CRYPTO_KMS_URI`.

## Removing it

Delete `backend/modules/crypto/` and these lines: `INSTALLED_APPS`, `CRYPTO_KMS_URI` and its `ADMIN_APP_GROUPS` line in `config/settings.py`, `KeysetInline` in `apps/authd/admin.py`, plus `CRYPTO_KMS_URI` in `backend/.env.example`, the `Makefile`'s install and CI. Only once nothing encrypted is left: without it, that data can't be read. Its table stays in the database until you drop it.
