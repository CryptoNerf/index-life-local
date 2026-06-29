// Public configuration. The Google OAuth client ID is a PUBLIC identifier
// (safe to ship in a browser app) — it only names this app to Google's OAuth;
// it grants no access by itself. Each user signs in with their own Google
// account and consents to the drive.file scope (files this app creates).

export const GOOGLE_CLIENT_ID =
  '991660860306-9ai6k2k5vcg4vuovklbr93ae7dbkotq0.apps.googleusercontent.com';

// Visible Drive folder the app creates and syncs through. Kept visible (not
// appDataFolder) so a desktop client mirroring the same Drive can share it.
export const DRIVE_FOLDER_NAME = 'index.life';

// Yandex OAuth app id (public). Implicit token flow in the browser; the app
// gets its own folder on Yandex.Disk via the cloud_api:disk.app_folder scope.
// Reachable in Russia without a VPN (unlike Google/Cloudflare).
export const YANDEX_CLIENT_ID = 'ace6472cc41f4101a181d5a94128f9b4';
