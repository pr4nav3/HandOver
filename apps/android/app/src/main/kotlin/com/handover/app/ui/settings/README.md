# Settings

SCREENS.md 17. `SettingsScreen(state, vm, modifier)` is the entry point; `SettingsMain` is the stateless page.

- `AppSettings` and `SettingsStore`: captions, caption size, haptics, voice next (off by default), camera source. Theme and Appearance live in ui/theme's `ThemeStore`.
- `ThemePicker`: all 14 themes as live miniatures, search, Appearance.
- `Parts.kt`: form rows, field, switch, segmented control, pushed bar. Shared with pairing, account and onboarding.
- `VoiceNext.kt`: the "next" and "back" matcher and a SpeechRecognizer listener for Learn to use.
