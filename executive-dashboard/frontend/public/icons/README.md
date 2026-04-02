# PWA Icons

Generate PWA icons from ifc_logo.png:

```bash
# Install icon generator
npm install -g pwa-asset-generator

# Generate icons
pwa-asset-generator ifc_logo.png ./icons --icon-only --background "#0f172a" --padding "10%"
```

Or manually create:
- icon-192x192.png (192x192px)
- icon-512x512.png (512x512px)

Use the IFC logo with a dark background (#0f172a) matching the app theme.
