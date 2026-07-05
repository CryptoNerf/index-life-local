# First-launch warnings (Gatekeeper / SmartScreen) — why, and how to remove them

## The short truth

When a user downloads an app that is **not signed with a paid developer
certificate**, both macOS and Windows show a one-time security warning
before the app is allowed to run. index.life is free and open-source and
ships unsigned, so users see this warning once.

**The app cannot dismiss this warning by itself.** The block happens
*before* any of the app's code runs — so an idea like "auto-run
`xattr -d com.apple.quarantine` on first launch" is impossible: the app
isn't allowed to launch, so it can't run the command that would unblock it.
It's a chicken-and-egg only two things can break:

1. **The user** clears the block manually (a workaround), or
2. **The developer signs + notarizes** the build (the real fix — no warning
   at all).

What the app *does* do automatically (`run.py`): once it is already running,
it clears its own quarantine / Mark-of-the-Web so **relaunches never
re-prompt** and copies of the app stay clean. This never affects the very
first launch.

---

## For users — the free workaround (no signature)

### macOS

- **Easiest:** double-click **`First Launch.command`** (shipped next to the
  app). It runs `xattr -cr` on the app and opens it. If macOS also warns
  about the `.command` file, right-click it → **Open**.
- **Manual:** Terminal →
  `xattr -dr com.apple.quarantine /Applications/index.life.app`
- **Via the UI (macOS 15 Sequoia):** try to open the app once, then
  System Settings → Privacy & Security → scroll to Security →
  **Open Anyway**.

### Windows

- Double-click the app; on the blue **"Windows protected your PC"** screen
  click **More info → Run anyway** (once).
- Or right-click the `.exe` → Properties → tick **Unblock** → OK.

---

## For the distributor — the real fix (removes the warning entirely)

### macOS: Developer ID signature + notarization

Requires an **Apple Developer** account ($99/yr). The build is already
**turn-key** — `build_macos.spec` reads the identity from the environment:

```bash
# 1. Sign at build time
export MACOS_CODESIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)"
# optional hardened-runtime entitlements:
export MACOS_ENTITLEMENTS_FILE="build/entitlements.plist"
pyinstaller build_macos.spec

# 2. Notarize the produced bundle
ditto -c -k --keepParent "dist/index.life.app" "index.life.app.zip"
xcrun notarytool submit index.life.app.zip \
    --keychain-profile NOTARY --wait          # set up once with `notarytool store-credentials`

# 3. Staple the ticket so it verifies offline
xcrun stapler staple "dist/index.life.app"
```

Notarization needs the **hardened runtime**; if it rejects the PyInstaller
binaries, add an entitlements file allowing unsigned executable memory
(the JIT/ctypes paths some deps use):

```xml
<!-- build/entitlements.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
  <key>com.apple.security.cs.disable-library-validation</key><true/>
</dict></plist>
```

After stapling, the app opens with a normal double-click and no warning.

### Windows: Authenticode code signing

Requires an OV or EV code-signing certificate (~$100–400/yr from a CA).
Sign the built `.exe` (and installer) with `signtool`:

```bat
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 ^
    /a "dist\index-life\index-life.exe"
```

An **EV** certificate clears SmartScreen immediately; an **OV** certificate
clears it after the download builds some reputation.

### Linux

AppImages aren't subject to Gatekeeper/SmartScreen — the user just makes the
file executable (`chmod +x`). Nothing to sign for the equivalent warning.
