# Training Navigator

A private, dependency-free media browser for this Windows PC. It opens on your local fixed disks and loads one folder at a time, so browsing remains fast even with a large training collection.

## What it does

- Starts with clear drive cards and a direct Training Library shortcut.
- Opens folders on demand with breadcrumbs, Back, Refresh, folder filtering, and kind-first sorting.
- Plays supported video and audio files; previews images, PDFs, text, and browser-readable files.
- Saves video position on the server, so the same video resumes on any signed-in Tailnet device.
- Keeps hidden, system, and the app's own data/publishing folders out of the browser.

## Private HTTPS address

On a device signed in to this Tailnet, open:

`https://your-device.your-tailnet.ts.net:8446`

Tailscale Serve provides the HTTPS certificate and proxies this private Tailnet address to `http://127.0.0.1:8796`. It is not exposed directly to the local network or public internet.

## Run and start after boot

For a one-off local session, run `./start-training-library.ps1` and open `http://localhost:8796`.

For a boot-time Windows service, open **Administrator PowerShell** once and run:

`Set-ExecutionPolicy -Scope Process Bypass; ./install-startup-service.ps1`

The installer creates the Windows startup task, restarts the app after a failure, and configures the dedicated private Tailnet HTTPS port.
