## Install

1. Download **AniGUI-{{VERSION}}-macOS-AppleSilicon.dmg** below, open it, and drag **AniGUI** onto the **Applications** folder.
   That's the only file you need: the `.sha256` file is the checksum AniGUI's updater uses, and the source code archives are added by GitHub.

   > ⚠️ **Your browser may block the download.** Chrome flags new apps that aren't notarized by Apple as "dangerous". AniGUI is open source and this file was built by GitHub Actions straight from the repo. To keep it, open `chrome://downloads` and choose **Keep** (it may be under the **⋮** menu), or download with **Safari**. Prefer not to? Build it yourself from the [README](https://github.com/JRodriguez-Luna/anigui#build-from-source).

2. **First launch:** AniGUI isn't notarized by Apple, so macOS blocks it the first time.
   Open it once, then go to **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.
   (Or in Terminal: `xattr -dr com.apple.quarantine /Applications/AniGUI.app`)
3. **Setup assistant:** click **Set up everything**. AniGUI installs ani-cli and the IINA player for you (no Homebrew or Terminal needed) and checks your connection. If your internet provider blocks the streaming site, it suggests Cloudflare WARP (free) or your own VPN.

This build is for Apple silicon Macs (M1 and newer). On an Intel Mac, build from source; see the README.

Your library and watch progress are kept outside the app, so updating is just replacing AniGUI.app.
