# Public source release gate

This repository is a sanitized source mirror. It may contain only files listed
in `.public-allowlist`.

Before every public commit and push, run:

```powershell
./tools/verify-public-release.ps1
```

The scanner rejects unallowlisted files, media, course documents, databases,
caches, transcodes, archives, secrets, local paths, hostnames, and private
deployment references. It does not copy, delete, commit, or push files.
