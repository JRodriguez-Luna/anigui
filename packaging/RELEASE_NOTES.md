## Install

1. Install the tools AniGUI drives (one time):
   ```sh
   brew install ani-cli fzf
   brew install --cask iina        # or: brew install mpv
   ```
2. Download **AniGUI-{{VERSION}}-macOS-AppleSilicon.zip** below, unzip it, and drag **AniGUI.app** into **Applications**.
3. **First launch:** AniGUI isn't notarized by Apple, so macOS blocks it the first time.
   Open it once, then go to **System Settings → Privacy & Security**, scroll down and click **Open Anyway**.
   (Or in Terminal: `xattr -dr com.apple.quarantine /Applications/AniGUI.app`)

This build is for Apple silicon Macs (M1 and newer). On an Intel Mac, build from source; see the README.

Your library and watch progress are kept outside the app, so updating is just replacing AniGUI.app.
