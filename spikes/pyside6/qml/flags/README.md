# Flag assets

Vendored from [lipis/flag-icons](https://github.com/lipis/flag-icons) at commit
`086f7e97d657358203916dbe84f61c2bccaa81eb`, using the `flags/4x3` SVG files.

| Clarify language asset | Upstream country asset |
| --- | --- |
| en.svg | us.svg (United States) |
| pt.svg | br.svg (Brazil) |
| es.svg | es.svg (Spain) |
| de.svg | de.svg (Germany) |
| ru.svg | ru.svg (Russia) |

Country artwork is unchanged. RoundedFlag.qml applies a Qt Quick Canvas clip
with a 3-pixel radius, without an inner border or SVG clipPath (unsupported by
Qt SVG). Flags display at 24 by 18 pixels, preserving the 4:3 aspect ratio. Filenames retain the
existing language mapping; language labels remain visible and accessible.

Only these five SVGs are included. No npm package, CSS, CDN or runtime download
is required. Copyright and permission notice: `licenses/flag-icons-MIT.txt`
(packaged with the application's third-party licenses).
