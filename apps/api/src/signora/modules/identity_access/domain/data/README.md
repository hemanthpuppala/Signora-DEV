# Bundled data

## `common-passwords.txt.gz`

The 100 000 most used passwords published by the UK National Cyber Security Centre, as distributed in
SecLists (`Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt`, MIT licence, © Daniel
Miessler) at commit `1a7bb9127eca9e6ff2fc0301c597fe6e16a0cb56`.

- Uncompressed SHA-256: `c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0`
- 99 840 lines, UTF-8. Compressed with `gzip -9 -n`.

Used by the password policy (Phase 2 LLD topic 3) to reject common passwords, compared case-insensitively.
To update: download the same file at a newer commit, record the commit and hash here, recompress.
