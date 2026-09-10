# Training Library Stream

A small, dependency-free web app that turns this training folder into a live, searchable catalog. Every page refresh scans the current folders and files; open browsers also receive a refresh signal within five seconds of a change.

## Run it

1. Open PowerShell in this folder.
2. Run `./start-training-library.ps1`.
3. Open `http://localhost:8794`.

The server deliberately scans only this project folder, skips hidden/system tooling folders, and never alters training content.

## Access it over Tailscale

Install and sign in to Tailscale on the Windows computer that holds this folder and on the other computer or mobile device. Enable MagicDNS and HTTPS Certificates once in the Tailnet DNS settings, then run the startup installer below. From another device on the same Tailnet, open:

`https://your-device.your-tailnet.ts.net`

Tailscale Serve provisions the trusted certificate and securely proxies `https://<device-name>.<tailnet>.ts.net:8446` to the local catalog. The app itself stays on `http://127.0.0.1:8794` and is not directly reachable from the LAN.

Do not use Tailscale Funnel for this app; Tailscale Serve keeps the catalog private to your Tailnet.

## Keep it running after restart

For a boot-time service that restarts after a failure, open **Administrator PowerShell** once and run:

`Set-ExecutionPolicy -Scope Process Bypass; ./install-startup-service.ps1`

This creates a Windows startup task, then configures Tailscale Serve to provide the catalog through trusted HTTPS on its dedicated external port `8446`.

## Next improvements

- Add thumbnails and direct file opening where supported.
- Save favourites and recently viewed courses.
- Add a password gate or Tailscale identity-aware sharing for selected people.
